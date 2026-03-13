# AI Helpline (Development Prototype)

AI Helpline is an experimental project exploring how conversational AI can automate responses to common information queries through voice-based interaction. The aim is to build an intelligent assistant capable of understanding user questions and providing quick automated responses.

This repository currently contains early development work related to **dataset preparation and training pipeline setup**.

---

## Current Progress

So far the following components have been implemented:

* Initial project environment setup
* Dataset creation for conversational training
* Data preparation scripts
* Structured question–answer dataset for training experiments
* Local testing setup for model training
* Fine Tuned of model completed
* Model converted to GGUF form, for easy access

The project is still under active development and additional modules will be integrated later.

---

## Repository Structure

```
AI-HELPLINE
│
├── data/
│   ├── college_data.json          # Structured conversational dataset
│   ├── training_data.csv          # Raw dataset used for experiments
│   ├── prepare.py                 # Dataset preprocessing pipeline
│   └── generate_variation.py      # Script for generating dataset variations
│
├── training/
│   ├── downloading_model.py       # Script to download the base model
│   ├── model_training_example.py  # Example fine-tuning workflow
│   └── convert_to_gguf_example.py # Example model conversion pipeline
│
├── .gitignore                     # Files excluded from version control
├── LICENSE                        # Project license
└── README.md                      # Documentation
```

---

## Development Status

This repository contains only the **initial research and prototype components**.
Certain implementation details and system architecture elements are intentionally not included.


Currently included components:

* dataset preparation scripts

* conversational training dataset

* training pipeline examples

* model conversion examples

Several implementation details and architecture components are intentionally not published at this stage.
---

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial 4.0 International License**.

Commercial use of this code or any derivative work is not permitted without explicit permission from the author.
