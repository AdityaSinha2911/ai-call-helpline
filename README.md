# AI Helpline (Development Prototype)

AI Helpline is an experimental project exploring how conversational AI systems can be trained to respond to structured queries using domain-specific datasets.

The primary focus of this repository is experimenting with **dataset preparation, training workflows, and model format conversion** for conversational language models.

At this stage, the repository contains **early development and research components** related to model experimentation and testing.

© 2026 Aditya Sinha. All rights reserved.

---

## Current Progress

So far the following components have been implemented:

- Initial project environment setup  
- Dataset creation for conversational training  
- Data preparation and preprocessing scripts  
- Structured question–answer dataset for training experiments  
- Local testing setup for model training  
- Example workflow for fine-tuning language models  
- Model conversion pipeline for exporting trained models into GGUF format  
- Prototype backend structure for experimentation  
- Guard modules for handling structured input/output validation  

The project is still under active development and additional modules will be integrated later.

---

## Repository Structure

```
AI-HELPLINE
│
├── backend/
│   ├── main.py
│   └── guards/
│       ├── input_guard.py
│       ├── output_guard.py
│       └── topic_guard.py
│
├── data/
│   ├── college_data.json          # Structured conversational dataset
│   ├── training_data.csv          # Raw dataset used for experiments
│   ├── prepare.py                 # Dataset preprocessing pipeline
│   └── generate_variation.py      # Script for generating dataset variations
│
├── scripts/
│   └── create_database.py         # Script for generating local testing database
│
├── training/
│   ├── downloading_model.py       # Script to download the base model
│   ├── model_training_example.py  # Example fine-tuning workflow
│   └── convert_to_gguf_example.py # Example model conversion pipeline
│
├── test_guards.py                 # Guard testing module
│
├── .gitignore                     # Files excluded from version control
├── LICENSE                        # Project license
├── Modelfile                      # Example runtime configuration
└── README.md                      # Project documentation
```

---

## Development Status

This repository contains only the **initial research and prototype components**.

Currently included components:

- dataset preparation scripts  
- conversational training dataset  
- example training pipelines  
- model conversion examples  
- backend prototype structure for testing  
- guard modules for experimental validation  

Large model files, training artifacts, and certain internal components are intentionally excluded from the repository.

Several implementation details and system architecture elements are intentionally not published at this stage.

---

## Research Focus

The experiments in this repository explore:

- conversational dataset structuring  
- prompt formatting strategies  
- supervised fine-tuning experiments  
- model conversion workflows  
- efficient model formats such as **GGUF** for local inference  

These experiments are intended to evaluate how language models adapt to **structured conversational datasets**.

---

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial 4.0 International License**.

Commercial use of this code or any derivative work is **not permitted without explicit permission from the author**.