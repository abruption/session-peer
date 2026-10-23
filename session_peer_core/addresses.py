"""Private selected recipients bound to an explicit route revision; no discovery."""
import base64
import copy
import unicodedata


ADDRESS_MAX_BYTES = 65536
ADDRESS_MAX_ENTRIES = 128
# Shared storage helpers enforce these limits on both reads and commits.
assert (ADDRESS_MAX_BYTES, ADDRESS_MAX_ENTRIES) == (PRESET_MAX_BYTES, PRESET_MAX_ENTRIES), "address/preset storage limits differ"


def _address_error(reason):
    return CcPeerError("address configuration refused: " + reason, {"reason": reason})


def _address_translate(error):
    reason = error.details.get("reason", "address_unsafe_storage")
    if reason.startswith("preset_"):
        reason = "address_" + reason[len("preset_"):]
    if reason == "address_commit_unconfirmed":
        return CcPeerError("address commit unconfirmed; inspect configuration before retrying", {"reason": reason})
    return _address_error(reason)


def address_platform():
    try:
        _preset_platform()
    except CcPeerError as error:
        raise _address_translate(error) from None


def _address_name(name):
    try:
        _preset_name(name)
    except CcPeerError as error:
        raise _address_translate(error) from None


def _address_hash(prefix, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return prefix + ":" + hashlib.sha256(raw).hexdigest()


def _address_selection_parts(preset, preset_rev, route, recipient, selection, ssh_host_key):
    _address_name(preset)
    try:
        route = preset_validate_entry(route)
        if preset_revision(preset, route) != preset_rev:
            raise _address_error("address_preset_revision_mismatch")
    except CcPeerError as error:
        raise _address_translate(error) from None
    if (type(recipient) is not dict or set(recipient) != {"agent", "target", "home"}
            or recipient["agent"] != route["agent"]):
        raise _address_error("address_invalid_recipient")
    agent, target, home = recipient["agent"], recipient["target"], recipient["home"]
    pattern = (r"claude:[1-9][0-9]*" if agent == "claude" else
               r"codex:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
    if (not isinstance(target, str) or len(target) > 128
            or re.fullmatch(pattern, target) is None):
        raise _address_error("address_invalid_recipient")
    if agent == "claude":
        if home is not None:
            raise _address_error("address_invalid_recipient")
    else:
        if (not isinstance(home, str) or not home or len(home) > 4096
                or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in home)
                or not PurePosixPath(home).is_absolute() or home.startswith("//") or "\\" in home
                or ".." in PurePosixPath(home).parts or str(PurePosixPath(home)) != home):
            raise _address_error("address_invalid_recipient")
    if (type(selection) is not dict or set(selection) != {
            "generationStatus", "targetGeneration", "writerRevision", "observationRevision"}):
        raise _address_error("address_invalid_selection")
    if agent == "claude":
        if (selection["generationStatus"] != "available" or selection["writerRevision"] is not None
                or not isinstance(selection["targetGeneration"], str)
                or re.fullmatch(r"tg1:[0-9a-f]{64}", selection["targetGeneration"]) is None):
            raise _address_error("address_invalid_selection")
    elif (selection["generationStatus"] != "unsupported" or selection["targetGeneration"] is not None
          or not isinstance(selection["writerRevision"], str)
          or re.fullmatch(r"aw1:[0-9a-f]{64}", selection["writerRevision"]) is None):
        raise _address_error("address_invalid_selection")
    if route["transport"] == "local":
        if ssh_host_key is not None:
            raise _address_error("address_invalid_host_key")
    else:
        if (not isinstance(ssh_host_key, str)
                or re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", ssh_host_key) is None):
            raise _address_error("address_invalid_host_key")
        try:
            digest = base64.b64decode(ssh_host_key[7:] + "=", validate=True)
            if len(digest) != 32 or base64.b64encode(digest).decode("ascii").rstrip("=") != ssh_host_key[7:]:
                raise ValueError()
        except (ValueError, TypeError):
            raise _address_error("address_invalid_host_key") from None
    return {"schemaVersion": 1, "preset": preset, "presetRevision": preset_rev,
            "route": route, "recipient": dict(recipient),
            "selection": {key: selection[key] for key in (
                "generationStatus", "targetGeneration", "writerRevision")},
            "sshHostKey": ssh_host_key}


def address_selection_revision(preset, presetRev, route, recipient, selection, sshHostKey):
    """Bind selected evidence to route and peer key, excluding its own digest."""
    return _address_hash("as1", _address_selection_parts(
        preset, presetRev, route, recipient, selection, sshHostKey))


def address_validate_label(label):
    if (not isinstance(label, str) or not label.strip() or len(label) > 128
            or unicodedata.normalize("NFC", label) != label
            or any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Zl", "Zp")
                   or ord(c) in (0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x3164, 0xFFA0)
                   or 0xFE00 <= ord(c) <= 0xFE0F or 0xE0100 <= ord(c) <= 0xE01EF for c in label)):
        raise _address_error("address_invalid_label")
    return label


def address_validate_entry(entry):
    if (type(entry) is not dict or set(entry) != {"bindingId", "label", "preset",
            "presetRevision", "route", "recipient", "selection", "sshHostKey"}):
        raise _address_error("address_invalid_entry")
    binding = entry["bindingId"]
    try:
        parsed = uuid.UUID(binding) if isinstance(binding, str) else None
        if parsed is None or str(parsed) != binding or parsed.version != 4:
            raise ValueError()
    except (ValueError, AttributeError):
        raise _address_error("address_invalid_binding_id") from None
    address_validate_label(entry["label"])
    revision = address_selection_revision(entry["preset"], entry["presetRevision"], entry["route"],
                                          entry["recipient"], entry["selection"], entry["sshHostKey"])
    if entry["selection"]["observationRevision"] != revision:
        raise _address_error("address_selection_revision_mismatch")
    return copy.deepcopy(entry)


def address_revision(name, entry):
    _address_name(name)
    return _address_hash("ab1", {"schemaVersion": 1, "name": name,
                                 "entry": address_validate_entry(entry)})


def _address_validate_entries(entries):
    labels = set()
    for name, entry in entries.items():
        _address_name(name)
        entry = address_validate_entry(entry)
        if entry["label"] in labels:
            raise _address_error("address_duplicate_label")
        labels.add(entry["label"])


def _address_decode(raw):
    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_preset_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if (type(value) is not dict or set(value) != {"schemaVersion", "addresses"}
                or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
                or type(value["addresses"]) is not dict):
            raise ValueError()
        entries = value["addresses"]
        if len(entries) > ADDRESS_MAX_ENTRIES:
            raise _address_error("address_capacity")
        _address_validate_entries(entries)
        return entries
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise _address_error("address_corrupt") from None
    except CcPeerError as error:
        raise _address_translate(error) from None


def address_read():
    """Read only; absence never initializes a directory, file, or lock."""
    directory = None
    failed = False
    try:
        _preset_platform()
        directory = _preset_directory()
        return {} if directory is None else _preset_read_at(directory, "addresses.json", _address_decode)
    except OSError:
        failed = True
        raise _address_error("address_unsafe_storage") from None
    except CcPeerError as error:
        failed = True
        raise _address_translate(error) from None
    except BaseException:
        failed = True
        raise
    finally:
        if directory is not None:
            try:
                _preset_cleanup(os.close, directory, preserve=failed)
            except CcPeerError as error:
                raise _address_translate(error) from None


def address_lookup(name):
    _address_name(name)
    entries = address_read()
    if name not in entries:
        raise _address_error("address_not_found")
    entry = entries[name]
    return entry, address_revision(name, entry)


def address_mutate(action, name, entry_withoutBindingId=None, expected_revision=None):
    _address_name(name)
    if action not in ("add", "reselect", "remove"):
        raise _address_error("address_invalid_action")
    entry = entry_withoutBindingId
    if action != "remove":
        if type(entry) is not dict or "bindingId" in entry:
            raise _address_error("address_invalid_entry")
        entry = address_validate_entry({**entry, "bindingId": str(uuid.uuid4())})
    try:
        return preset_mutate("replace" if action == "reselect" else action, name, entry, expected_revision,
            _storage={"filename": "addresses.json", "lockname": "addresses.lock", "collection": "addresses",
                      "decoder": _address_decode, "validate_entry": address_validate_entry,
                      "revision": address_revision, "revision_prefix": "ab1", "result_key": "entry",
                      "validate_entries": _address_validate_entries})
    except CcPeerError as error:
        raise _address_translate(error) from None
