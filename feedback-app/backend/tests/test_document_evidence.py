import io
import json
import tarfile
import unittest
from unittest.mock import patch

from app.document_evidence import DocumentEvidenceIndex


class FakeBlob:
    def __init__(self, name, elements):
        self.name = name
        self.payload = json.dumps(elements).encode("utf-8")

    def download_as_bytes(self):
        return self.payload


class FakeStorageClient:
    def __init__(self, blobs, bundle_data=None):
        self.blobs = blobs
        self.bundle_data = bundle_data
        self.listed = False

    def bucket(self, bucket_name):
        self.bucket_name = bucket_name
        return self

    def blob(self, name):
        self.bundle_name = name
        return FakeBundle(self.bundle_data)

    def list_blobs(self, bucket_name, prefix):
        self.listed = True
        self.requested_bucket = bucket_name
        self.requested_prefix = prefix
        return [blob for blob in self.blobs if blob.name.startswith(prefix)]


class FakeBundle:
    def __init__(self, data):
        self.data = data

    def exists(self, client=None):
        return self.data is not None

    def download_as_bytes(self):
        return self.data


class GcsDocumentEvidenceTest(unittest.TestCase):
    def test_loads_vlm_raw_json_from_gcs_with_source_provenance(self):
        blob = FakeBlob("parsed_docs_vlm/bop_raw.json", [{
            "element_id": "element-38",
            "type": "NarrativeText",
            "text": "BOP scheduled job begins running at 12:00 PM",
            "metadata": {"filename": "bop-training.pptx", "page_number": 38},
        }])
        client = FakeStorageClient([blob])
        with patch("app.document_evidence.storage.Client", return_value=client):
            index = DocumentEvidenceIndex("", "", "gs://rca-docs/parsed_docs_vlm")

        results = index.search("When does the BOP scheduled job run?")

        self.assertEqual(client.requested_bucket, "rca-docs")
        self.assertEqual(client.requested_prefix, "parsed_docs_vlm/")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["evidence_id"], "D1")
        self.assertEqual(results[0]["source"], "bop-training.pptx")
        self.assertEqual(results[0]["page"], "38")
        self.assertEqual(results[0]["origin"], "vlm")
        self.assertIn("12:00 PM", results[0]["excerpt"])

    def test_gcs_reader_ignores_non_raw_objects(self):
        chunks = FakeBlob("parsed_docs_vlm/bop_chunks.json", [])
        client = FakeStorageClient([chunks])
        with patch("app.document_evidence.storage.Client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "No parsed VLM"):
                DocumentEvidenceIndex("", "", "gs://rca-docs/parsed_docs_vlm")

    def test_vlm_gcs_source_takes_precedence_over_fast_gcs_source(self):
        blobs = [
            FakeBlob("parsed_docs_vlm/shared_raw.json", [{
                "element_id": "vlm-element",
                "type": "NarrativeText",
                "text": "VLM version: scheduled BOP run at noon",
                "metadata": {"filename": "shared.pptx", "page_number": 3},
            }]),
            FakeBlob("parsed_docs_fast/shared_raw.json", [{
                "element_id": "fast-element",
                "type": "NarrativeText",
                "text": "Fast version of shared source",
                "metadata": {"filename": "shared.pptx", "page_number": 3},
            }]),
            FakeBlob("parsed_docs_fast/fast-only_raw.json", [{
                "element_id": "fast-only-element",
                "type": "NarrativeText",
                "text": "Fast parser only source with separate information",
                "metadata": {"filename": "fast-only.pdf", "page_number": 1},
            }]),
        ]
        client = FakeStorageClient(blobs)
        with patch("app.document_evidence.storage.Client", return_value=client):
            index = DocumentEvidenceIndex(
                "",
                "",
                "gs://rca-docs/parsed_docs_vlm",
                "gs://rca-docs/parsed_docs_fast",
            )

        shared = [record for record in index.records if record["source"] == "shared.pptx"]
        fast_only = [record for record in index.records if record["source"] == "fast-only.pdf"]
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0]["origin"], "vlm")
        self.assertEqual(len(fast_only), 1)
        self.assertEqual(fast_only[0]["origin"], "fast")

    def test_prefers_compressed_gcs_bundle_to_individual_object_downloads(self):
        elements = [{
            "element_id": "element-38",
            "type": "NarrativeText",
            "text": "BOP scheduled job begins running at 12:00 PM",
            "metadata": {"filename": "bop-training.pptx", "page_number": 38},
        }]
        payload = json.dumps(elements).encode("utf-8")
        bundle_buffer = io.BytesIO()
        with tarfile.open(fileobj=bundle_buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo("bop_raw.json")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

        client = FakeStorageClient([], bundle_data=bundle_buffer.getvalue())
        with patch("app.document_evidence.storage.Client", return_value=client):
            index = DocumentEvidenceIndex("", "", "gs://rca-docs/parsed_docs_vlm")

        results = index.search("When does the BOP scheduled job run?")
        self.assertEqual(client.bundle_name, "parsed_docs_vlm/_raw_bundle.tar.gz")
        self.assertFalse(client.listed)
        self.assertEqual(results[0]["source"], "bop-training.pptx")


if __name__ == "__main__":
    unittest.main()
