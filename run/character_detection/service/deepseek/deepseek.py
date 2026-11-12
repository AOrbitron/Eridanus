import io
import os
import base64
from PIL import Image, ImageSequence

# 缓存已加载的模型实例，避免每次调用重复加载
_DEEPSEEK_MODEL = None
_TRANSFORM = None

def get_transform():
    global _TRANSFORM
    if _TRANSFORM is None:
        from torchvision import transforms
        _TRANSFORM = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
    return _TRANSFORM

def load_model(model_path, device):
    import torch
    import torch.nn as nn
    from torchvision import models

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")

    model = models.resnet50()
    num_features = model.fc.in_features
    model.fc = nn.Linear(num_features, 2)
    state = torch.load(model_path, map_location=device)
    model.load_state_dict(state)
    model = model.to(device)
    model.eval()
    return model

def get_model():
    global _DEEPSEEK_MODEL
    if _DEEPSEEK_MODEL is None:
        import torch
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        script_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(script_dir, 'deepseek.pth')
        _DEEPSEEK_MODEL = (load_model(model_path, device), device)
    return _DEEPSEEK_MODEL

def predict_frame(frame, model, transform, device):
    import torch
    frame_tensor = transform(frame).unsqueeze(0).to(device)
    with torch.no_grad():
        output = model(frame_tensor)
        _, pred = torch.max(output, 1)
    return pred.item() == 1

def predict_image_or_gif(image_bytes, model, transform, device):
    image_stream = io.BytesIO(image_bytes)
    try:
        with Image.open(image_stream) as image:
            if image.format == 'GIF':
                frame_idx = 0
                for frame in ImageSequence.Iterator(image):
                    # 每隔最多3帧抽检一次，减轻CPU负荷
                    if frame_idx % 2 == 0:
                        rgb_frame = frame.convert('RGB')
                        try:
                            if predict_frame(rgb_frame, model, transform, device):
                                return True
                        finally:
                            rgb_frame.close()
                    frame_idx += 1
                    if frame_idx >= 15:  # 最多检查前15帧
                        break
                return False
            else:
                rgb_image = image.convert('RGB')
                try:
                    return predict_frame(rgb_image, model, transform, device)
                finally:
                    rgb_image.close()
    finally:
        image_stream.close()

def detect_deepseek_from_base64(base64_string):
    image_bytes = base64.b64decode(base64_string)
    model, device = get_model()
    transform = get_transform()
    try:
        return predict_image_or_gif(image_bytes, model, transform, device)
    except Exception as e:
        return False

def main(base64_string):
    result = detect_deepseek_from_base64(base64_string)
    return 1 if result else 0
