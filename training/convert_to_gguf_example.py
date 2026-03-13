"""
Example script to convert a HuggingFace model to GGUF format
for use with llama.cpp or Ollama.

Note:
This is only an example pipeline.
Actual conversion code is not public.
Actual model weights are not included in this repository.
"""

import os
import subprocess


# Path where merged HuggingFace model is stored
MODEL_PATH = "./merged_model"

# Output GGUF file
OUTPUT_FILE = "./college.gguf"


def convert_to_gguf():

    print("Starting GGUF conversion...")

    command = [
        "python",
        "llama.cpp/convert_hf_to_gguf.py",
        MODEL_PATH,
        "--outfile",
        OUTPUT_FILE,
        "--outtype",
        "q8_0"
    ]

    subprocess.run(command)

    print("Conversion complete!")
    print("Output file:", OUTPUT_FILE)


if __name__ == "__main__":
    convert_to_gguf()