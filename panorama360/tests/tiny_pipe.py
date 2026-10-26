"""Pipeline SDXL diminuto con pesos aleatorios para probar el motor sin descargar nada."""

import json

import torch
from diffusers import AutoencoderKL, EulerDiscreteScheduler, StableDiffusionXLPipeline, UNet2DConditionModel
from transformers import CLIPTextConfig, CLIPTextModel, CLIPTextModelWithProjection, CLIPTokenizer


def bytes_to_unicode():
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, map(chr, cs)))


def _tokenizer(folder):
    chars = list(bytes_to_unicode().values())
    vocab = {"<|startoftext|>": 0, "<|endoftext|>": 1}
    for char in chars:
        vocab.setdefault(char, len(vocab))
        vocab.setdefault(char + "</w>", len(vocab))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "vocab.json").write_text(json.dumps(vocab))
    (folder / "merges.txt").write_text("#version: 0.2\n")
    return CLIPTokenizer(str(folder / "vocab.json"), str(folder / "merges.txt"), pad_token="<|endoftext|>", model_max_length=77)


def build(folder):
    torch.manual_seed(0)
    unet = UNet2DConditionModel(
        block_out_channels=(32, 64), layers_per_block=1, sample_size=16, in_channels=4, out_channels=4,
        down_block_types=("DownBlock2D", "CrossAttnDownBlock2D"), up_block_types=("CrossAttnUpBlock2D", "UpBlock2D"),
        attention_head_dim=(2, 4), use_linear_projection=True, addition_embed_type="text_time",
        addition_time_embed_dim=8, transformer_layers_per_block=(1, 1), projection_class_embeddings_input_dim=80,
        cross_attention_dim=64, norm_num_groups=1,
    )
    vae = AutoencoderKL(
        block_out_channels=[16, 16, 16, 16], in_channels=3, out_channels=3, layers_per_block=1,
        down_block_types=["DownEncoderBlock2D"] * 4, up_block_types=["UpDecoderBlock2D"] * 4,
        latent_channels=4, norm_num_groups=8, sample_size=64,
    )
    config = CLIPTextConfig(
        bos_token_id=0, eos_token_id=1, pad_token_id=1, hidden_size=32, intermediate_size=37, layer_norm_eps=1e-5,
        num_attention_heads=4, num_hidden_layers=2, vocab_size=600, hidden_act="gelu", projection_dim=32,
    )
    scheduler = EulerDiscreteScheduler(
        beta_start=0.00085, beta_end=0.012, steps_offset=1, beta_schedule="scaled_linear", timestep_spacing="leading"
    )
    tokenizer = _tokenizer(folder)
    pipe = StableDiffusionXLPipeline(
        vae=vae, text_encoder=CLIPTextModel(config), text_encoder_2=CLIPTextModelWithProjection(config),
        tokenizer=tokenizer, tokenizer_2=tokenizer, unet=unet, scheduler=scheduler,
    )
    pipe.set_progress_bar_config(disable=True)
    return pipe
