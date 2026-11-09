"""Isolated real SDK client; talks only to this checkout's synthetic policy."""
import asyncio
from contextlib import asynccontextmanager
from importlib.metadata import version
import json
import sys


@asynccontextmanager
async def connect(server_python, server_path, policy_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=server_python,
        args=[server_path, '--config', policy_path])
    if version('mcp').split('.')[0] == '2':
        from mcp import Client
        # Exercise modern discovery on SDK 2 servers and fallback negotiation
        # on SDK 1 servers, rather than forcing all clients into legacy mode.
        async with Client(params, mode='auto') as client:
            yield client, client.protocol_version, client.server_capabilities
    else:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                initialized = await client.initialize()
                yield client, initialized.protocolVersion, initialized.capabilities


async def main():
    async with connect(*sys.argv[1:4]) as (client, protocol, capabilities):
        tools = await client.list_tools()
        inventory = await client.call_tool('list_destinations', {})
        refused = await client.call_tool('send_message', {
            'destination': 'local', 'target': 'synthetic-fixture', 'message': 'never delivered'})
        preflight = await client.call_tool('preflight_send', {
            'destination': 'local', 'target': 'synthetic-fixture', 'message': 'never delivered'})
        diagnostics = await client.call_tool('diagnose_destination', {
            'destination': 'local', 'active_probe': True})
        subscription_error = None
        if protocol == '2026-07-28':
            from mcp import MCPError, types
            try:
                await client.session.send_request(types.SubscriptionsListenRequest(
                    params=types.SubscriptionsListenRequestParams(
                        notifications=types.SubscriptionFilter(tools_list_changed=True))),
                    types.Result, request_read_timeout_seconds=2)
            except MCPError as exc:
                subscription_error = exc.code
            else:
                raise AssertionError('subscription request unexpectedly accepted')
        report = {'sdk': version('mcp'), 'protocol': protocol,
            'capabilities': capabilities.model_dump(mode='json', by_alias=True, exclude_none=True),
            'subscription_error': subscription_error,
            'tools': tools.model_dump(mode='json', by_alias=True),
            'inventory': inventory.model_dump(mode='json', by_alias=True),
            'refused': refused.model_dump(mode='json', by_alias=True),
            'preflight': preflight.model_dump(mode='json', by_alias=True),
            'diagnostics': diagnostics.model_dump(mode='json', by_alias=True)}
    async with connect(*sys.argv[1:3], sys.argv[4]) as (client, bounded_protocol, _):
        bounded = await client.call_tool('list_destinations', {})
        report['bounded'] = bounded.model_dump(mode='json', by_alias=True)
        report['bounded_protocol'] = bounded_protocol
    print(json.dumps(report))


if __name__ == '__main__':
    asyncio.run(main())
