FROM python:3.11-slim AS build
RUN pip install app
FROM python:3.11-slim
COPY --from=build /app /app
USER nonroot
CMD ["python", "app.py"]
