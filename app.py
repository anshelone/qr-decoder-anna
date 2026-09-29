from flask import Flask, render_template, request, jsonify
import base64
import zlib
import lzma
import bz2
import brotli
import zstandard
import lz4.frame
import os

app = Flask(__name__)

ALGORITHMS = {
    "auto": "Автоопределение",
    "none": "Без сжатия",
    "zlib": "zlib",
    "lzma": "lzma",
    "bz2": "bz2",
    "brotli": "brotli",
    "zstandard": "zstandard",
    "lz4": "lz4",
}


def try_decode(raw: bytes, algorithm: str) -> str:
    if algorithm == "none":
        data = raw
    elif algorithm == "zlib":
        data = zlib.decompress(raw)
    elif algorithm == "lzma":
        data = lzma.decompress(raw)
    elif algorithm == "bz2":
        data = bz2.decompress(raw)
    elif algorithm == "brotli":
        data = brotli.decompress(raw)
    elif algorithm == "zstandard":
        data = zstandard.ZstdDecompressor().decompress(raw)
    elif algorithm == "lz4":
        data = lz4.frame.decompress(raw)
    else:
        raise ValueError("Неизвестный алгоритм")
    return data.decode("utf-8")


def looks_like_plain_text(s: str) -> bool:
    if not s:
        return True
    printable = sum(ch.isprintable() or ch in "\\n\\r\\t" for ch in s)
    return printable / len(s) > 0.95


def decode_payload(payload: str, algorithm: str):
    payload = payload.strip()
    if not payload:
        raise ValueError("QR-код пустой.")

    # QR-коды без сжатия с сайта содержат обычный текст напрямую.
    if algorithm == "none":
        return payload, "Без сжатия"

    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception:
        if algorithm == "auto" and looks_like_plain_text(payload):
            return payload, "Без сжатия"
        raise ValueError("В QR-коде нет корректной Base64-последовательности для сжатых данных.")

    if algorithm != "auto":
        try:
            return try_decode(raw, algorithm), ALGORITHMS[algorithm]
        except Exception as exc:
            raise ValueError(f"Не удалось расшифровать как {ALGORITHMS[algorithm]}: {exc}")

    # Сначала пробуем форматы сайта. Порядок выбран по характерным форматам данных.
    for candidate in ("zlib", "lzma", "bz2", "brotli", "zstandard", "lz4"):
        try:
            text = try_decode(raw, candidate)
            if looks_like_plain_text(text):
                return text, ALGORITHMS[candidate]
        except Exception:
            pass

    # На случай, если QR был просто Base64-текстом.
    try:
        text = raw.decode("utf-8")
        if looks_like_plain_text(text):
            return text, "Base64 → UTF-8"
    except Exception:
        pass

    raise ValueError("Не удалось определить способ сжатия. Выбери алгоритм вручную.")


@app.get("/")
def home():
    return render_template("decoder.html")


@app.get("/manifest.json")
def manifest():
    return app.send_static_file("manifest.json")


@app.get("/service-worker.js")
def service_worker():
    response = app.send_static_file("service-worker.js")
    response.headers["Content-Type"] = "application/javascript"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@app.post("/api/decode")
def api_decode():
    data = request.get_json(silent=True) or {}
    payload = data.get("payload", "")
    algorithm = data.get("algorithm", "auto")
    if not isinstance(payload, str) or not payload.strip():
        return jsonify({"error": "QR-код не содержит данных."}), 400
    if algorithm not in ALGORITHMS:
        return jsonify({"error": "Неизвестный алгоритм."}), 400
    try:
        text, method = decode_payload(payload, algorithm)
        return jsonify({"text": text, "method": method, "payload": payload})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
