// Avatar pre-upload pipeline: read → decode → center-crop to square →
// resize to 256x256 → re-encode to JPEG (quality 0.85) → return data URL.
// Output is small enough (~30-60 KB) to store inline on the user row, and
// matches the backend's avatar_data_url validator.

const MAX_SOURCE_BYTES = 8 * 1024 * 1024; // 8 MB — guard against huge uploads
const TARGET_SIZE = 256;
const JPEG_QUALITY = 0.85;

export class AvatarProcessingError extends Error {}

export async function processAvatarFile(file: File): Promise<string> {
  if (!file.type.startsWith('image/')) {
    throw new AvatarProcessingError('Please choose an image file.');
  }
  if (file.size > MAX_SOURCE_BYTES) {
    throw new AvatarProcessingError('Image must be smaller than 8 MB.');
  }

  const dataUrl = await readAsDataURL(file);
  const image = await loadImage(dataUrl);

  const sourceSize = Math.min(image.naturalWidth, image.naturalHeight);
  if (sourceSize === 0) {
    throw new AvatarProcessingError('That image could not be decoded.');
  }
  const sx = (image.naturalWidth - sourceSize) / 2;
  const sy = (image.naturalHeight - sourceSize) / 2;

  const canvas = document.createElement('canvas');
  canvas.width = TARGET_SIZE;
  canvas.height = TARGET_SIZE;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new AvatarProcessingError('Your browser does not support image processing.');
  }
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(image, sx, sy, sourceSize, sourceSize, 0, 0, TARGET_SIZE, TARGET_SIZE);

  return canvas.toDataURL('image/jpeg', JPEG_QUALITY);
}

function readAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new AvatarProcessingError('Could not read the file.'));
    reader.readAsDataURL(file);
  });
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new AvatarProcessingError('That image could not be decoded.'));
    img.src = src;
  });
}
