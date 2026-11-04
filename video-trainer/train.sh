#!/bin/sh
# Trains one half of a Wan 2.2 I2V video LoRA from data/lora/NAME/video_dataset (made by
# `python -m dreamfeed video-prep NAME`):
#   train.sh NAME high|low|both [STEPS]
# Wan 2.2 has two experts: "high" makes the motion (noisy early steps), "low" the detail.
# They're trained one at a time so only one 14B model is in memory. The result goes to
# models/loras/video-NAME-PART.safetensors, in the format ComfyUI reads.
# While it runs, data/lora/.training tells the worker to hold generation (GPU and RAM).
set -eu
name=${1:?usage: NAME high|low|both [STEPS]} part=${2:?usage: NAME high|low|both [STEPS]} steps=${3:-1500}
lock=/data/lora/.training
if [ -z "${VIDEO_TRAIN_HOLDING:-}" ]; then
  echo "video-$name-$part $(date -u +%s)" > "$lock"
  trap 'rm -f "$lock"' EXIT
fi
if [ "$part" = both ]; then
  VIDEO_TRAIN_HOLDING=1 sh "$0" "$name" high "$steps"
  touch "$lock"   # the worker treats a lock older than 8 hours as stale
  VIDEO_TRAIN_HOLDING=1 sh "$0" "$name" low "$steps"
  exit 0
fi
: "${VIDEO_TRAIN_RES:?set VIDEO_TRAIN_RES}" "${VIDEO_TRAIN_FRAMES:?set VIDEO_TRAIN_FRAMES}"
: "${VIDEO_TRAIN_BLOCKS_TO_SWAP:?set VIDEO_TRAIN_BLOCKS_TO_SWAP}"
base=/data/lora/$name
w=/train-models
case $part in
  high) dit=wan2.2_i2v_high_noise_14B_fp16.safetensors tmin=900 tmax=1000 ;;
  low)  dit=wan2.2_i2v_low_noise_14B_fp16.safetensors  tmin=0   tmax=900 ;;
  *) echo "part must be high or low" >&2; exit 2 ;;
esac
for f in $dit wan2.1_vae.pth umt5-xxl-enc-bf16.pth; do
  [ -f $w/$f ] || { echo "missing $w/$f (see README: video LoRAs)" >&2; exit 2; }
done
[ -d $base/video_dataset ] || { echo "no $base/video_dataset; run video-prep first" >&2; exit 2; }

cfg=$base/video-dataset.toml
cat > $cfg <<EOF
[general]
resolution = [$VIDEO_TRAIN_RES, $VIDEO_TRAIN_RES]
caption_extension = ".txt"
batch_size = 1
enable_bucket = true
bucket_no_upscale = false

[[datasets]]
video_directory = "$base/video_dataset"
cache_directory = "$base/video_cache"
target_frames = [$VIDEO_TRAIN_FRAMES]
frame_extraction = "uniform"
frame_sample = 3
EOF

cd /musubi
python src/musubi_tuner/wan_cache_latents.py --dataset_config $cfg --vae $w/wan2.1_vae.pth \
  --i2v --vae_cache_cpu --skip_existing
python src/musubi_tuner/wan_cache_text_encoder_outputs.py --dataset_config $cfg \
  --t5 $w/umt5-xxl-enc-bf16.pth --fp8_t5 --batch_size 4 --skip_existing

out=$base/video_out
accelerate launch --num_cpu_threads_per_process 1 --mixed_precision fp16 \
  src/musubi_tuner/wan_train_network.py \
  --task i2v-A14B --dit $w/$dit --dataset_config $cfg \
  --sdpa --mixed_precision fp16 --fp8_base --fp8_scaled --gradient_checkpointing --force_v2_1_time_embedding \
  --blocks_to_swap $VIDEO_TRAIN_BLOCKS_TO_SWAP \
  --optimizer_type adamw8bit --learning_rate 2e-4 \
  --network_module networks.lora_wan --network_dim 32 --network_alpha 32 \
  --timestep_sampling shift --discrete_flow_shift 5.0 \
  --min_timestep $tmin --max_timestep $tmax --preserve_distribution_shape \
  --max_data_loader_n_workers 0 \
  --max_train_steps $steps --save_every_n_steps 250 --save_precision bf16 --seed 42 \
  --output_dir $out --output_name video-$name-$part

python src/musubi_tuner/convert_lora.py --input $out/video-$name-$part.safetensors \
  --output /models/loras/video-$name-$part.safetensors --target other
echo "trained /models/loras/video-$name-$part.safetensors"
