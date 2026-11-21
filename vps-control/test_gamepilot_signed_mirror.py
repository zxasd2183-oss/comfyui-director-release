#!/usr/bin/env python3
"""Offline tests for GamePilot's isolated VPS signed-update mirror."""
import base64
import hashlib
import importlib.util
import io
import os
import plistlib
import stat
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gamepilot_signed_mirror", ROOT / "gamepilot_signed_mirror.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_archive(version, b64, malicious_link=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        contents = plistlib.dumps({
            "CFBundleIdentifier": "cn.gamepilot.unified.mac",
            "CFBundleVersion": version,
            "SUPublicEDKey": b64,
            "SURequireSignedFeed": True,
        })
        z.writestr("GamePilot.app/Contents/Info.plist", contents)
        z.writestr("GamePilot.app/Contents/Frameworks/Sparkle.framework/Versions/B/Sparkle", b"stub")
        z.writestr("GamePilot.app/Contents/Resources/LICENSE", b"Test license." * 1200)
        if malicious_link is not None:
            link = zipfile.ZipInfo("GamePilot.app/Contents/Frameworks/Sparkle.framework/Versions/Current")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(link, malicious_link)
    return stream.getvalue()


def signed_xml(private, version, size, zip_signature, *, github_url=False):
    ET.register_namespace("sparkle", "http://www.andymatuschak.org/xml-namespaces/sparkle")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    item = ET.SubElement(channel, "item")
    archive = f"GamePilot-mac-arm64-v{version}.zip"
    if github_url:
        url = f"https://github.com/{module.REPO}/releases/download/gamepilot-mac-v{version}/{archive}"
    else:
        url = f"https://sync.borealos.cn/downloads/{archive}"
    ET.SubElement(item, "enclosure", {
        "url": url,
        "length": str(size),
        module.SPARKLE_NS + "version": version,
        module.SPARKLE_NS + "edSignature": base64.b64encode(zip_signature).decode(),
    })
    data = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    envelope = (b"<!-- sparkle-signatures:\n" +
                b"edSignature: " + base64.b64encode(private.sign(data)) +
                b"\nlength: " + str(len(data)).encode() + b"\n-->\n")
    return data + envelope


class MirrorTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.directory = Path(td.name)
        self.private = Ed25519PrivateKey.generate()
        pub = self.private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        self.b64 = base64.b64encode(pub).decode()
        self.patchers = [
            patch.object(module, "PUB", self.private.public_key()),
            patch.object(module, "PUBLIC_KEY_B64", self.b64),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)
        self.version = "0.4.2"
        self.name = f"GamePilot-mac-arm64-v{self.version}.zip"
        self.zip = make_archive(self.version, self.b64, "B")
        (self.directory / self.name).write_bytes(self.zip)
        self.digest = hashlib.sha256(self.zip).hexdigest()
        self.feed = signed_xml(self.private, self.version, len(self.zip), self.private.sign(self.zip))

    def test_signed_feed_verifies_payload_and_archive_identity(self):
        version, name, size, signature = module.signed_feed(self.feed)
        self.assertEqual((version, name, size), (self.version, self.name, len(self.zip)))
        self.private.public_key().verify(signature, self.zip)
        with self.assertRaises(InvalidSignature):
            module.signed_feed(self.feed.replace(b"0.4.2", b"0.4.3", 1))

    def test_raw_github_zip_url_refused_even_if_signed(self):
        xml = signed_xml(self.private, self.version, len(self.zip),
                         self.private.sign(self.zip), github_url=True)
        with self.assertRaisesRegex(ValueError, "VPS-origin"):
            module.signed_feed(xml)

    def test_sparkle_framework_relative_symlink_allowed(self):
        module.validate_zip(self.directory / self.name, self.version)
        bad = self.directory / "bad.zip"
        bad.write_bytes(make_archive(self.version, self.b64, "../../../../../../etc/passwd"))
        with self.assertRaisesRegex(ValueError, "escapes Sparkle framework"):
            module.validate_zip(bad, self.version)

    def test_publish_and_refuse_same_version_mutation(self):
        release = (self.version, self.name, len(self.zip), self.digest)
        with patch.object(module, "latest_release", return_value=release), \
             patch.object(module, "fetch_appcast", return_value=self.feed):
            self.assertTrue(module.sync(self.directory))
            self.assertTrue(module.sync(self.directory))
        feedfile = self.directory / module.FEED_NAME
        self.assertEqual(feedfile.read_bytes(), self.feed)
        other = signed_xml(self.private, self.version, len(self.zip),
                           self.private.sign(self.zip))
        # Same signed update, different XML bytes should be refused.
        other = other.replace(b"<?xml", b"<?XML")
        # A malformed replacement would fail signature validation, likewise refused.
        with patch.object(module, "latest_release", return_value=release), \
             patch.object(module, "fetch_appcast", return_value=other):
            with self.assertRaises((ValueError, InvalidSignature, ET.ParseError)):
                module.sync(self.directory)
        self.assertEqual(feedfile.read_bytes(), self.feed)

    def test_symlink_target_destination_rejected(self):
        feed = self.directory / module.FEED_NAME
        feed.symlink_to(self.directory / self.name)
        release = (self.version, self.name, len(self.zip), self.digest)
        with patch.object(module, "latest_release", return_value=release), \
             patch.object(module, "fetch_appcast", return_value=self.feed):
            with self.assertRaisesRegex(ValueError, "Symlinked GamePilot feed"):
                module.sync(self.directory)


if __name__ == "__main__":
    unittest.main()
