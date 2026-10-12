"""Fixed PDF renderer subprocess; accepts local paths, with no shell or tools."""

import argparse
import json
from pathlib import Path

from .production_render import clean_pdf, render_pdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("selection")
    parser.add_argument("output")
    parser.add_argument("--page-preview", type=int)
    args = parser.parse_args()
    regions = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    if args.page_preview:
        information = {}
        images = render_pdf(Path(args.source), [], page_number=args.page_preview, information=information)
        images[0].save(args.output, format="PNG")
        Path(args.output + ".json").write_text(json.dumps(information), encoding="utf-8")
    else:
        Path(args.output).write_bytes(clean_pdf(render_pdf(Path(args.source), regions)))


if __name__ == "__main__":
    main()
