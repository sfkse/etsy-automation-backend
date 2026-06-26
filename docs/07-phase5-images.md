# Phase 5

From the Full Spec. Implement in order. Each step ends with a validation block.

---

## PHASE 5: AI IMAGE PIPELINE (Multi-Workflow)

### Step 5.1: Abstract Image Generator Interface
**Goal:** Common interface for all 3 image models.

**Implementation:**
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from PIL import Image

@dataclass
class ImageGenerationRequest:
    reference_image: Image.Image  # Background-removed jewelry
    prompt: str
    style_hint: str  # e.g. "professional jewelry photography, soft natural lighting"
    num_outputs: int = 1
    seed: int | None = None
    extra_params: dict = None

@dataclass
class ImageGenerationResult:
    image: Image.Image
    model_name: str
    cost_estimate: float
    metadata: dict


class AbstractImageGenerator(ABC):
    @abstractmethod
    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def cost_per_image(self) -> float:
        pass
```

**Validation:**
- Interface is well-defined
- Subclasses must implement all abstract methods
- Type hints complete

---

### Step 5.2: Background Removal (Preprocessing)
**Goal:** Remove background from Reksven photo before AI generation.

**Implementation:**
- Use `rembg` library (local, no API cost)
- Function `remove_background(image_path) -> Image.Image` (returns transparent PNG)
- Save preprocessed image to `./data/images/{SKU}/preprocessed/`

**Validation:**
- Input real jewelry photo, output is clean jewelry with transparent BG
- Quality is good (no jagged edges)

---

### Step 5.3: Gemini Image Generator
**Goal:** Implement using Gemini 2.5 Flash Image (Nano Banana).

**Implementation:**
```python
from google import genai
from google.genai import types

class GeminiImageGenerator(AbstractImageGenerator):
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
    
    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        # Save reference image temporarily
        ref_bytes = io.BytesIO()
        request.reference_image.save(ref_bytes, format='PNG')
        
        # Call Gemini with multi-image input
        full_prompt = f"{request.prompt}\n\nStyle: {request.style_hint}"
        
        response = self.client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=[
                types.Part.from_bytes(data=ref_bytes.getvalue(), mime_type='image/png'),
                full_prompt
            ]
        )
        
        # Parse image from response
        results = []
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                img = Image.open(io.BytesIO(part.inline_data.data))
                results.append(ImageGenerationResult(
                    image=img,
                    model_name=self.model_name,
                    cost_estimate=self.cost_per_image,
                    metadata={"prompt": full_prompt}
                ))
        
        return results
    
    @property
    def model_name(self) -> str:
        return "gemini-2.5-flash-image"
    
    @property
    def cost_per_image(self) -> float:
        return 0.039  # current Gemini pricing, check at runtime
```

**Validation:**
- Provide test jewelry image
- Generate 1 lifestyle scene
- Output is reasonable
- Cost is logged

---

### Step 5.4: OpenAI Image Generator
**Goal:** Implement using gpt-image-1.

**Implementation:**
- Use openai SDK
- Use image edit endpoint (better for reference-based generation)
- Same interface as Gemini

```python
class OpenAIImageGenerator(AbstractImageGenerator):
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
    
    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        ref_bytes = io.BytesIO()
        request.reference_image.save(ref_bytes, format='PNG')
        ref_bytes.seek(0)
        
        response = self.client.images.edit(
            model="gpt-image-1",
            image=ref_bytes,
            prompt=f"{request.prompt}. {request.style_hint}",
            n=request.num_outputs,
            size="1024x1024"
        )
        
        results = []
        for img_data in response.data:
            img_bytes = base64.b64decode(img_data.b64_json)
            img = Image.open(io.BytesIO(img_bytes))
            results.append(ImageGenerationResult(
                image=img,
                model_name=self.model_name,
                cost_estimate=self.cost_per_image,
                metadata={"prompt": request.prompt}
            ))
        
        return results
    
    @property
    def model_name(self) -> str:
        return "gpt-image-1"
    
    @property
    def cost_per_image(self) -> float:
        return 0.04
```

**Validation:**
- Same as Gemini test
- Compare output side-by-side with Gemini

---

### Step 5.5: Flux (fal.ai) Image Generator
**Goal:** Implement using Flux + IP-Adapter via fal.ai.

**Implementation:**
- Use `fal-client` SDK
- Use Flux LoRA endpoint with IP-Adapter
- IP-Adapter scale 0.85-0.95 for jewelry preservation

```python
import fal_client

class FluxImageGenerator(AbstractImageGenerator):
    def __init__(self, api_key: str):
        os.environ['FAL_KEY'] = api_key
    
    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        # Upload reference image to fal.ai
        ref_url = fal_client.upload_image(request.reference_image)
        
        # Call Flux with IP-Adapter
        result = await fal_client.run_async(
            "fal-ai/flux/dev/image-to-image",
            arguments={
                "image_url": ref_url,
                "prompt": f"{request.prompt}. {request.style_hint}",
                "strength": 0.85,  # Higher = more variation, lower = more preservation
                "num_images": request.num_outputs,
                "seed": request.seed,
            }
        )
        
        results = []
        for img_info in result['images']:
            img = await download_image(img_info['url'])
            results.append(ImageGenerationResult(
                image=img,
                model_name=self.model_name,
                cost_estimate=self.cost_per_image,
                metadata={"prompt": request.prompt, "seed": img_info.get('seed')}
            ))
        
        return results
    
    @property
    def model_name(self) -> str:
        return "flux-dev-img2img"
    
    @property
    def cost_per_image(self) -> float:
        return 0.025
```

**Validation:**
- Generate image, jewelry detail preserved
- IP-Adapter scale tested at different values

---

### Step 5.6: Workflow Factory & Selector
**Goal:** Runtime selection of which workflow to use.

**Implementation:**
```python
class ImageWorkflowFactory:
    _workflows = {
        "gemini": GeminiImageGenerator,
        "openai": OpenAIImageGenerator,
        "flux": FluxImageGenerator,
    }
    
    @classmethod
    def get(cls, workflow_name: str, settings) -> AbstractImageGenerator:
        if workflow_name not in cls._workflows:
            raise ValueError(f"Unknown workflow: {workflow_name}")
        
        api_key_map = {
            "gemini": settings.GEMINI_API_KEY,
            "openai": settings.OPENAI_API_KEY,
            "flux": settings.FAL_API_KEY,
        }
        
        return cls._workflows[workflow_name](api_key_map[workflow_name])
    
    @classmethod
    def get_all(cls, settings) -> dict[str, AbstractImageGenerator]:
        return {name: cls.get(name, settings) for name in cls._workflows}
```

**Validation:**
- Factory returns correct instance for each name
- Invalid name raises clear error

---

### Step 5.7: Comparison Workflow
**Goal:** Run same prompt through all 3 workflows for side-by-side test.

**Implementation:**
- Route: `POST /products/{sku}/generate-comparison`
- Generates 1 image per workflow with same prompt
- Saves to `./data/images/{SKU}/comparison/{workflow_name}.png`
- Returns a comparison view

**UI:**
- Show 3 images side by side
- Show cost, speed for each
- User can vote/select best one
- Selection saved to product metadata

**Validation:**
- All 3 workflows run successfully
- Comparison page loads
- User can select preferred workflow per product

---

### Step 5.8: Production Image Generation
**Goal:** Generate the 5-6 AI lifestyle images for the listing.

**Implementation:**
- After workflow selection, generate full set with selected workflow
- Prompts (use fixed templates):
  - "Woman wearing the necklace, soft natural lighting, neutral background"
  - "Necklace on marble surface flat lay, minimalist styling"
  - "Hand opening gift box containing necklace, lifestyle"
  - "Macro detail shot of necklace pendant"
  - "Young woman in cafe wearing necklace, candid lifestyle"
- Save each with proper naming: `{SKU}-lifestyle-{n}.jpg`
- Save with SEO filename pattern (kebab-case keywords)

**Critical:**
- Maintain **Section 1.11 rule**: at least 3 real Reksven photos must remain in the final image set.
- AI images are supplementary, not replacement.

**Validation:**
- Product has 8+ total images (3 real + 5 AI)
- All have file names following SEO pattern
- All sized 2000x2000

---

### Step 5.9: Alt Text Generator
**Goal:** Auto-generate alt text for each image.

**Implementation:**
- For each image, generate alt text based on:
  - Product main keyword (from carrier pillar + features)
  - Image position rank (1-9)
  - Image type (lifestyle, detail, size, box)
- Use rules from Section 1.4

```python
def generate_alt_text(product: Product, image: ProductImage) -> str:
    """Generate SEO alt text based on rank and product."""
    main_keyword = build_main_keyword(product)  # e.g. "gold plated cross necklace"
    
    if image.rank == 1:
        return f"{main_keyword} - main view"
    elif image.rank in [2, 3]:
        return f"{main_keyword} - color variation {image.rank}"
    elif image.rank in [4, 5]:
        return f"{main_keyword} - size and material details"
    elif image.rank in [6, 7]:
        return f"{main_keyword} - gift for {product.recipient}"
    elif image.rank == 8:
        return f"{main_keyword} - gift box presentation"
    else:
        return f"{main_keyword}"
```

**Validation:**
- All 9 image positions have meaningful alt text
- Alt text includes main keyword
- Length 50-150 chars each

---