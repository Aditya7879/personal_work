"""Add environment/batch/endpoint-test storage and seed ONLY the existing configured targets."""
from app.bigquery import BigQueryRepository


def main():
    repo = BigQueryRepository()
    repo.ensure_environment_schema()
    print("Environment settings, batch and endpoint-test schema ready:", repo.dataset_ref)
    print("Existing configured targets retained. No feedback changed and no retests queued.")


if __name__ == "__main__":
    main()
