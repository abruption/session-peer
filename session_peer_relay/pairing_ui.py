"""Explicit owner-terminal confirmation; pairing credentials never use argv/JSON."""
import json
import os
import re
import signal
import termios
import threading
import uuid

from .identity import fingerprint
from .pairing_links import encode_link, decode_link, link_digest
from .store import Rejected
from .wire import direct_address, validate_relay_url


class OfferOutcomeUnknown(Rejected):
    """Only a public preallocated ID survives uncertain local completion."""
    def __init__(self, offer_id, *, interrupted=False):
        super().__init__('pairing_offer_outcome_unknown')
        self.offer_id = offer_id
        self.interrupted = interrupted


def offer_failure(exc):
    if type(exc) is not OfferOutcomeUnknown:
        return None
    try:
        ident = uuid.UUID(exc.offer_id)
        valid = ident.version == 4 and str(ident) == exc.offer_id
    except (AttributeError, TypeError, ValueError):
        valid = False
    result = {'ok': False, 'reason': 'pairing_offer_outcome_unknown',
        'status': 'unknown', 'updated': False, 'retryAllowed': False}
    if valid:
        result['offerId'] = exc.offer_id
    return result


class Terminal:
    def __enter__(self):
        try:
            self.fd = os.open('/dev/tty', os.O_RDWR | getattr(os, 'O_NOCTTY', 0))
            if not os.isatty(self.fd):
                os.close(self.fd)
                raise OSError()
        except OSError:
            raise Rejected('pairing_terminal_required') from None
        return self

    def __exit__(self, *unused):
        os.close(self.fd)

    def show(self, text):
        raw = (text + '\n').encode('utf-8')
        while raw:
            count = os.write(self.fd, raw)
            if count <= 0:
                raise Rejected('pairing_terminal_unavailable')
            raw = raw[count:]

    def read(self, prompt, *, secret=False, limit=256):
        # Noncanonical input avoids the usual 4096-byte canonical TTY line cap.
        # Read one byte at a time so a following confirmation is never consumed.
        saved = termios.tcgetattr(self.fd)
        settings = termios.tcgetattr(self.fd)
        settings[3] &= ~(termios.ICANON | termios.ECHO | termios.ECHONL)
        settings[6][termios.VMIN], settings[6][termios.VTIME] = 1, 0
        raw = bytearray()
        previous_handler = None
        if threading.current_thread() is threading.main_thread():
            previous_handler = signal.getsignal(signal.SIGINT)
            # asyncio.run's cancellation handler cannot interrupt a synchronous
            # TTY read. Raise directly so Ctrl-C restores terminal mode promptly.
            if previous_handler != signal.SIG_IGN:
                signal.signal(signal.SIGINT, signal.default_int_handler)
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, settings)
            self.show(prompt)
            while True:
                value = os.read(self.fd, 1)
                if not value or value == b'\x04':
                    raise Rejected('pairing_input_cancelled')
                if value in (b'\n', b'\r'):
                    break
                if value in (b'\x7f', b'\x08'):
                    if raw:
                        raw.pop()
                    continue
                raw.extend(value)
                if len(raw) > limit:
                    raise Rejected('pairing_input_too_large')
            try:
                return raw.decode('ascii')
            except UnicodeDecodeError:
                raise Rejected('invalid_pairing_input') from None
        finally:
            try:
                try:
                    termios.tcflush(self.fd, termios.TCIFLUSH)
                finally:
                    termios.tcsetattr(self.fd, termios.TCSANOW, saved)
            finally:
                if previous_handler is not None:
                    signal.signal(signal.SIGINT, previous_handler)
            self.show('')


def routes_from_args(args):
    routes = {}
    if args.direct:
        direct_address(args.direct)
        routes['direct'] = args.direct
    if args.relay:
        validate_relay_url(args.relay)
        routes['relay'] = args.relay
    if not routes:
        raise Rejected('route_required')
    return routes


def identity_text(store, intended=None):
    result = {'localPrincipal': store.device, 'localKeyFingerprint': store.key_id,
              'localGeneration': store.generation}
    if intended is not None:
        result['intendedClient'] = intended
    return json.dumps(result, ensure_ascii=True, sort_keys=True)


def create_offer(store, args, *, offer_id=None, before_create=None, created=None):
    if not getattr(args, 'show_link', False):
        raise Rejected('pairing_explicit_link_display_required')
    routes = routes_from_args(args)
    identity = store.offer_identity(args.peer_key)
    ident, attempted, invitation = offer_id or str(uuid.uuid4()), False, None
    try:
        with Terminal() as terminal:
            terminal.show(identity_text(store, identity))
            terminal.show('Pairing preserves receiving target policy. Confirm these identities through a trusted channel.')
            if terminal.read('Type yes to confirm your identity and this intended client key:') != 'yes':
                raise Rejected('pairing_identity_not_confirmed')
            if before_create is not None:
                before_create()
            attempted = True
            invitation = store.create_offer(routes, args.peer_key,
                expected_identity=identity, offer_id=ident)
            if created is not None:
                created(invitation['id'])
            terminal.show('Private one-use link; expires in ten minutes. Avoid terminal recording and clipboard/browser history:')
            terminal.show(encode_link(invitation, args.peer_key))
        return store.offer_status(invitation['id'])
    except (Exception, KeyboardInterrupt) as exc:
        if not attempted or (isinstance(exc, Rejected) and invitation is None):
            raise
        raise OfferOutcomeUnknown(ident, interrupted=isinstance(exc, KeyboardInterrupt)) from None


def receive_link(store, route):
    with Terminal() as terminal:
        raw = terminal.read('Paste private pairing link (hidden):', secret=True, limit=16 * 1024)
        try:
            invitation, intended_key = decode_link(raw)
        except ValueError:
            raise Rejected('invalid_pairing_link') from None
        if intended_key != store.key_id:
            raise Rejected('pairing_wrong_client_key')
        digest = link_digest(raw)
        routes = invitation['routes']
        selected = ('direct' if 'direct' in routes else 'relay') if route == 'auto' else route
        if selected not in routes:
            raise Rejected('setup_invitation_route_unavailable')
        receiver_key = fingerprint(invitation['certificate'])
        receiver_identity = store.receiver_offer_identity(invitation, digest, intended_key)
        if (receiver_identity['principal'] != invitation['device']
                or receiver_identity['generation'] != invitation.get('keyGeneration', 0)):
            raise Rejected('unproven_principal')
        terminal.show(identity_text(store))
        expected = terminal.read('Enter receiver fingerprint obtained independently through a trusted channel:')
        if not re.fullmatch(r'[a-f0-9]{64}', expected) or expected != receiver_key:
            raise Rejected('pairing_receiver_identity_mismatch')
        terminal.show(json.dumps({'receiverPrincipal': invitation['device'],
            'receiverKeyFingerprint': receiver_key, 'receiverGeneration': invitation.get('keyGeneration', 0),
            'routes': routes}, ensure_ascii=True, sort_keys=True))
        if terminal.read('Type yes to confirm your identity and pair with this receiver under its policy:') != 'yes':
            raise Rejected('pairing_identity_not_confirmed')
    return invitation, intended_key, digest, selected
