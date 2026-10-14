import unittest
from unittest.mock import Mock

from app.bigquery import BigQueryRepository


class BigQueryRepositoryTest(unittest.TestCase):
    def test_appends_use_completed_load_jobs_not_streaming_inserts(self):
        client = Mock()
        job = Mock()
        client.load_table_from_json.return_value = job
        repository = BigQueryRepository(client=client)

        repository._insert_rows("project.dataset.table", [{"id": "1"}])

        client.load_table_from_json.assert_called_once()
        job.result.assert_called_once_with()
        client.insert_rows_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
