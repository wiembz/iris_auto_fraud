FROM apache/airflow:3.3.0-python3.12

COPY requirements-airflow.txt /tmp/requirements-airflow.txt

RUN pip install --no-cache-dir \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.0/constraints-3.12.txt" \
    -r /tmp/requirements-airflow.txt
