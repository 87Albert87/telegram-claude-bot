#!/usr/bin/env python3
"""
Gemini image generation script for nano-banana-pro (Gemini 3 Pro Image)
Compatible with Docker deployment
"""
import argparse
import os
import sys


def generate_image(prompt: str, filename: str, resolution: str = "1K"):
    """Generate an image using Gemini image models via google-genai SDK."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")

    client = genai.Client(api_key=api_key)

    # Choose model based on resolution needs
    if resolution == "4K":
        model_name = "gemini-3-pro-image-preview"
    else:
        model_name = "gemini-2.5-flash-image"

    # Detect aspect ratio from prompt
    aspect_ratio = "1:1"
    if "landscape" in prompt.lower() or "wide" in prompt.lower():
        aspect_ratio = "16:9"
    elif "portrait" in prompt.lower() or "tall" in prompt.lower():
        aspect_ratio = "9:16"

    # Enhanced prompt for better results
    enhanced_prompt = f"{prompt}. High quality, detailed, professional."

    response = client.models.generate_content(
        model=model_name,
        contents=enhanced_prompt,
    )

    if not response.parts:
        raise ValueError("No image generated in response")

    for part in response.parts:
        if part.inline_data is not None:
            image = part.as_image()
            image.save(filename)
            print(f"Image saved to {filename}")
            return

    raise ValueError("No image data found in response")


def main():
    parser = argparse.ArgumentParser(description="Generate images using Gemini")
    parser.add_argument("--prompt", required=True, help="Image generation prompt")
    parser.add_argument("--filename", required=True, help="Output filename")
    parser.add_argument("--resolution", default="1K", choices=["1K", "2K", "4K"], help="Image resolution")

    args = parser.parse_args()

    try:
        generate_image(args.prompt, args.filename, args.resolution)
        print("Success", file=sys.stderr)
    except Exception as e:
        print(f"Failed: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
