"""Native lifecycle stand-in. Used only by isolated process boundary tests."""
import json
import os
import sys
import time

for line in sys.stdin:
    value = json.loads(line)
    if value.get('method') == 'initialize':
        print(json.dumps({'id': 1, 'result': {}}), flush=True)
    elif value.get('method') == 'thread/resume':
        assert set(value['params']) == {'threadId', 'cwd', 'excludeTurns'}
        tid = value['params']['threadId']
        mode = os.environ.get('WAKE_TEST_MODE', 'complete')
        if mode == 'reject':
            print(json.dumps({'id':2,'error':{'message':'project not trusted'}}), flush=True)
        elif mode == 'approval':
            print(json.dumps({'id':99,'method':'item/commandExecution/requestApproval','params':{}}), flush=True)
        elif mode == 'malformed':
            print('not json', flush=True)
        else:
            print(json.dumps({'id':2,'result':{'thread':{'id':tid}}}), flush=True)
            if mode == 'timeout':
                time.sleep(60)
            else:
                print(json.dumps({'method':'turn/completed','params':{'threadId':tid,'turn':{'status':'completed'}}}), flush=True)
