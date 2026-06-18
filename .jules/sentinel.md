## 2024-06-18 - Remove ast.literal_eval fallback
**Vulnerability:** ast.literal_eval was used as a fallback for parsing JSON strings when json.loads failed.
**Learning:** Using ast.literal_eval allows Python-specific literals which can cause unwanted behavior or DoS risks, violating strict JSON structures.
**Prevention:** Strictly enforce JSON structure parsing with json.loads and ignore candidates that fail JSON decoding.
