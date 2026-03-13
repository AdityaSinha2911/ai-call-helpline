#I had done model fine tuning on Google Collab, this is just a exapmle code


# Simple LoRA fine-tuning script

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from datasets import Dataset
from trl import SFTTrainer, SFTConfig
import json

#  Load Training Data 
with open("training_data.json", "r") as f:
    data = json.load(f)

dataset = Dataset.from_list(data)

# Load Base Model
MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"

# I used bnb for Bit and Bytes configuration, it is used for freeing up memory, as fine tuning a model is heavy load task.
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True
)

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    quantization_config=bnb_config,
    device_map="auto"
)

# Prepare model for LoRA training
model = prepare_model_for_kbit_training(model)

# LoRA Configuration, it used for training a model, without training the whole model, it make small layers of data.
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj"],
    task_type="CAUSAL_LM"
)

model = get_peft_model(model, lora_config)

# Making Trainer Ready
trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    dataset_text_field="text",
    args=SFTConfig(
        output_dir="./trained_model",
        num_train_epochs=3,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        logging_steps=10,
        bf16=True
    ),
    max_seq_length=512
)

#Initialize Training
trainer.train()

#Saving Model
trainer.save_model("./trained_model")
tokenizer.save_pretrained("./trained_model")

print("Training finished. Model saved in ./trained_model")