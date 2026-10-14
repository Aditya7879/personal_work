from app.bigquery import BigQueryRepository


if __name__ == "__main__":
    repository = BigQueryRepository()
    repository.ensure_schema()
    print(f"Initialized {repository.dataset_ref}")
