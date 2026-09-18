import argparse
import base64
import io
from pathlib import Path

from azure.identity import AzureCliCredential, get_bearer_token_provider
from openai import AzureOpenAI
from PIL import Image


PROJECT_ENDPOINT = (
    "https://foundry-jva-002.cognitiveservices.azure.com/"
)
MODEL = "gpt-image-2.5-sunburst"
EMERALD = (20, 97, 76)
WHITE = (255, 255, 255)
CORAL = (216, 91, 67)
BLUE = (49, 107, 138)
PALETTE = (EMERALD, WHITE, CORAL, BLUE)
PROMPT = """
Create a finished 1:1 app icon for Elle, a thoughtful AI companion.

Create one bold, minimal monogram that reads simultaneously as an uppercase E
and a friendly front-facing baby elephant. Use a clean white geometric E as the
main silhouette. Shape its lower stroke into one unmistakable upward-curling
elephant trunk. Add two broad, simple elephant ears behind the E, with flat
coral inner-ear shapes (#D85B43), and one tiny flat blue forehead accent
(#316B8A). Center the mark on a flat deep emerald field (#14614C). Use only
large solid shapes, softened corners, and generous negative space so the E,
ears, and trunk remain recognizable at 32 pixels. The feeling should be calm,
intelligent, warm, and gently playful.

Strict constraints: flat vector-like artwork using only emerald, white, coral,
and blue; exactly one letter E; no eyes, no mouth, no tusks, no full body, no
person, no brain, no circuit, no sparkles, no leaves, no ornament, no pattern,
no thin lines, no border, no frame, no gradient, no shadow, no glow, no texture,
no perspective, no mockup, and no photographic elements. Fill the square
canvas edge to edge.
""".strip()


def export_teams_assets(image_data: bytes, output_dir: Path) -> None:
    generated = Image.open(io.BytesIO(image_data)).convert("RGB")
    palette = Image.new("P", (1, 1))
    palette.putpalette(
        [channel for color in PALETTE for channel in color] + [0] * (768 - len(PALETTE) * 3)
    )
    flattened = generated.quantize(
        palette=palette,
        dither=Image.Dither.NONE,
    ).convert("RGB")

    output_dir.mkdir(parents=True, exist_ok=True)
    color = Image.new("RGB", (192, 192), EMERALD)
    color.paste(flattened.resize((176, 176), Image.Resampling.LANCZOS), (8, 8))
    color.save(output_dir / "color.png", optimize=True)

    foreground = Image.new("L", flattened.size)
    foreground.putdata([0 if pixel == EMERALD else 255 for pixel in flattened.getdata()])
    alpha = Image.new("L", (32, 32))
    alpha.paste(foreground.resize((28, 28), Image.Resampling.LANCZOS), (2, 2))
    outline = Image.new("RGBA", (32, 32), (*WHITE, 0))
    outline.putalpha(alpha)
    outline.save(output_dir / "outline.png", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--endpoint", default=PROJECT_ENDPOINT)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--teams-dir", type=Path)
    args = parser.parse_args()

    credential = AzureCliCredential(process_timeout=120)
    token_provider = get_bearer_token_provider(
        credential,
        "https://cognitiveservices.azure.com/.default",
    )
    with AzureOpenAI(
        azure_endpoint=args.endpoint.rstrip("/"),
        api_version="2025-04-01-preview",
        azure_ad_token_provider=token_provider,
    ) as client:
        response = client.images.generate(
            model=args.model,
            prompt=PROMPT,
            size="1024x1024",
            quality="high",
            output_format="png",
            background="opaque",
        )

    encoded = response.data[0].b64_json
    if not encoded:
        raise RuntimeError("Foundry image generation returned no image data")
    image_data = base64.b64decode(encoded)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image_data)
    if args.teams_dir is not None:
        export_teams_assets(image_data, args.teams_dir)
    print(args.output.resolve())


if __name__ == "__main__":
    main()