from PIL import Image, ImageDraw, ImageFont
import os

root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
out_path = os.path.join(root, 'app', 'static', 'img', 'logo.png')
os.makedirs(os.path.dirname(out_path), exist_ok=True)

img = Image.new('RGBA', (640, 180), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
font_path = os.path.join('C:\\', 'Windows', 'Fonts', 'arial.ttf')
font = ImageFont.truetype(font_path, 82) if os.path.exists(font_path) else ImageFont.load_default()
text = 'LEYLY'
bbox = draw.textbbox((0, 0), text, font=font)
text_w = bbox[2] - bbox[0]
text_h = bbox[3] - bbox[1]
x = (img.width - text_w) / 2
y = (img.height - text_h) / 2 - 4
draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
img.save(out_path)
print(out_path)
