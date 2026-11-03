#!/bin/bash
# Usage (from the dreamfeed folder):
#   docker compose run --rm trainer NAME BASE_CHECKPOINT [STEPS]
# Trains models/loras/style-NAME.safetensors from data/lora/NAME/dataset (made by
# `python -m dreamfeed lora-prep`). While it runs, data/lora/.training tells the worker
# to hold generation so the two don't fight over the GPU.
set -euo pipefail
name=${1:?usage: NAME BASE_CHECKPOINT [STEPS]}
base=${2:?usage: NAME BASE_CHECKPOINT [STEPS]}
steps=${3:-2000}
data=/data/lora/$name/dataset
[ -d "$data" ] || { echo "train: $data missing; run lora-prep first" >&2; exit 1; }
[ -f "/models/checkpoints/$base" ] || { echo "train: /models/checkpoints/$base not found" >&2; exit 1; }
lock=/data/lora/.training
echo "$name $(date -u +%s)" > "$lock"
trap 'rm -f "$lock"' EXIT
accelerate launch --num_cpu_threads_per_process=4 sdxl_train_network.py \
  --pretrained_model_name_or_path="/models/checkpoints/$base" \
  --train_data_dir="$data" --caption_extension=.txt \
  --output_dir=/models/loras --output_name="style-$name" --save_model_as=safetensors \
  --resolution=1024,1024 --enable_bucket --min_bucket_reso=512 --max_bucket_reso=1536 --bucket_no_upscale \
  --network_module=networks.lora --network_dim=16 --network_alpha=8 --network_train_unet_only \
  --optimizer_type=AdamW8bit --learning_rate=1e-4 --lr_scheduler=cosine --lr_warmup_steps=100 \
  --max_train_steps="$steps" --save_every_n_steps=500 --train_batch_size=1 \
  --mixed_precision=bf16 --save_precision=fp16 --no_half_vae --sdpa \
  --gradient_checkpointing --cache_latents --cache_latents_to_disk --cache_text_encoder_outputs \
  --max_data_loader_n_workers=2 --seed=42
echo "train: wrote /models/loras/style-$name.safetensors"
