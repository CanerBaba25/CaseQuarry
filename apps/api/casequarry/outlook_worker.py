import json
import sys
from dataclasses import asdict
from pathlib import Path

from .outlook import MsgError, decode_msg
from .parsers import Parsed


def main():
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    root = Path(job["root"])
    try:
        result = decode_msg(Path(job["path"]), job["filename"], job["limits"])
    except MsgError as error:
        result = Parsed("email", job["filename"], state="failed", error=str(error))
    except Exception as error:
        result = Parsed("email", job["filename"], state="failed", error="MSG_PARSE_FAILED", metadata={"failure_type": type(error).__name__})
    attachments, result.attachments = result.attachments, []
    data = asdict(result)
    if result.date_utc:
        data["date_utc"] = result.date_utc.isoformat()
    for index, (name, content) in enumerate(attachments):
        (root / f"attachment-{index}.bin").write_bytes(content)
        data["attachments"].append(name)
    (root / "result.json").write_text(json.dumps(data), encoding="utf-8")


if __name__ == "__main__":
    main()
