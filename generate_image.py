#!/usr/bin/env python3
"""
Gemini image generation script for nano-banana-pro (Gemini 3 Pro Image)
Compatible with Docker deployment
"""
import argparse
import os
import sys
import google.generativeai as genai


def generate_image(prompt: str, filename: str, resolution: str = "1K"):
    """Generate an image using Gemini 3 Pro Image (Nano Banana Pro)."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")

    # Configure Gemini
    genai.configure(api_key=api_key)

    # Choose model based on resolution needs
    # gemini-3-pro-image-preview for high quality
    # gemini-2.5-flash-image for faster generation
    if resolution == "4K":
        model_name = "gemini-3-pro-image-preview"
        quality = "high"
    else:
        model_name = "gemini-2.5-flash-image"
        quality = "standard"

    # Map resolution to aspect ratio and size
    aspect_ratio = "1:1"  # default square
    if "landscape" in prompt.lower() or "wide" in prompt.lower():
        aspect_ratio = "16:9"
    elif "portrait" in prompt.lower() or "tall" in prompt.lower():
        aspect_ratio = "9:16"

    # Generate image
    model = genai.GenerativeModel(model_name)

    # Build generation config
    generation_config = {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 40,
        "max_output_tokens": 8192,
    }

    # Enhanced prompt for better results
    enhanced_prompt = f"{prompt}. High quality, detailed, professional."

    try:
        response = model.generate_content(
            enhanced_prompt,
            generation_config=generation_config,
        )

        # Extract image from response
        if not response.parts:
            raise ValueError("No image generated in response")

        # Save the image
        for part in response.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                image_data = part.inline_data.data
                with open(filename, 'wb') as f:
                    f.write(image_data)
                print(f"Image saved to {filename}")
                return

        raise ValueError("No image data found in response")

    except Exception as e:
        print(f"Error generating image: {str(e)}", file=sys.stderr)
        raise


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
