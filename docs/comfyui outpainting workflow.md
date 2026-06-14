Sharing my automated comfyui outpainting workflow
Workflow Included
What is this?

An outpaint workflow that takes a single image as an input and gives acceptable results with limited VRAM, if you have the patience.

r/StableDiffusion - Sharing my automated comfyui outpainting workflow
Workflow: https://gist.github.com/molbal/e788df0adbf44dc7489620a084cf92eb

How does it work?

It scales the image down to 1 megapixel size (So that my 8GB VRAM GPU can bear with it) then pads it to the sides

It uses Florence 2 to make two descriptions: a shorter one and a longer one

An LLM (running locally with Ollama) takes the extended descriptions and enriches it so that more details are added to the side (padded areas)

Flux Fill is used, with the enriched prompt to do the single pass

Then, the entire image is passed to Flux Fill again, with the entire image passed to it as a composition step, with the vaguer, original shorter positive description Florence wrote. (This could perhaps be changed to an image-to-image workflow.)

Scale it up and save it.

Things to look out for using this workflow:

Downscaling and then upscaling reduces the quality of smaller details in images with fine details. (e.g. buildings from the distance, text)

The LLM is not managed by ComfyUI itself, so it does not unload Florence to make space for in VRAM, so it often runs from CPU+RAM, making it a bit slower.

This is not a quick workflow, on my laptop (RTX 3080 Laptop 8GB + 48GB RAM) outpainting a single picture takes about 5 minutes.

Examples

r/StableDiffusion - Sharing my automated comfyui outpainting workflow
r/StableDiffusion - Sharing my automated comfyui outpainting workflow
r/StableDiffusion - Sharing my automated comfyui outpainting workflow
This is an example where the loss of detail is visible:

r/StableDiffusion - Sharing my automated comfyui outpainting workflow