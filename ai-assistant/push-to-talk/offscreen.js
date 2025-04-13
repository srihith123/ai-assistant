// offscreen.js

// Listen for messages from the background script
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.target !== 'offscreen') {
        return; // Ignore messages not intended for this document
    }
    
    if (request.type === "crop_image") {
        console.log("Offscreen: Received crop_image request");
        handleCropRequest(request.dataUrl, request.rect, request.dpr)
            .then(croppedDataUrl => {
                sendResponse({ success: true, croppedDataUrl: croppedDataUrl });
            })
            .catch(error => {
                console.error("Offscreen: Cropping error:", error);
                sendResponse({ success: false, error: error.message || "Unknown cropping error" });
            });
        return true; // Indicate async response
    }
    
    return false;
});

async function handleCropRequest(dataUrl, rect, dpr) {
    console.log(`Offscreen: Starting crop operation for rect: ${JSON.stringify(rect)}, dpr: ${dpr}`);
    dpr = dpr || 1; // Default DPR to 1 if not provided
    if (!dataUrl || !rect) {
        throw new Error("Missing dataUrl or rectangle for cropping.");
    }

    try {
        // 1. Create an ImageBitmap from the data URL
        const response = await fetch(dataUrl);
        const blob = await response.blob();
        const imageBitmap = await createImageBitmap(blob);
        console.log(`Offscreen: ImageBitmap created (${imageBitmap.width}x${imageBitmap.height}).`);

        // 2. Create an OffscreenCanvas, scaled by DPR
        const scaledWidth = Math.round(rect.width * dpr);
        const scaledHeight = Math.round(rect.height * dpr);
        const canvas = new OffscreenCanvas(scaledWidth, scaledHeight);
        const ctx = canvas.getContext('2d');
        console.log(`Offscreen: Canvas created ${scaledWidth}x${scaledHeight} (scaled by DPR).`);

        // 3. Define source coordinates, scaled by DPR
        const sx = Math.round(rect.x * dpr);
        const sy = Math.round(rect.y * dpr);
        const sWidth = scaledWidth; // Use already scaled width/height
        const sHeight = scaledHeight;

        // 4. Draw the relevant portion of the ImageBitmap to the canvas
        console.log(`Offscreen: Drawing image from source rect (${sx}, ${sy}, ${sWidth}, ${sHeight}) to canvas dest (0, 0, ${scaledWidth}, ${scaledHeight})`);
        ctx.drawImage(imageBitmap, 
            sx, sy, sWidth, sHeight, 
            0, 0, scaledWidth, scaledHeight
        );
        console.log("Offscreen: Image drawn to canvas.");

        // 5. Convert the canvas content back to a data URL (PNG)
        const croppedBlob = await canvas.convertToBlob({ type: 'image/png' });
        console.log("Offscreen: Canvas converted to Blob.");

        // 6. Convert Blob to Data URL to send back
        const reader = new FileReader();
        return new Promise((resolve, reject) => {
            reader.onloadend = () => {
                console.log("Offscreen: Blob converted back to Data URL.");
                resolve(reader.result);
            };
            reader.onerror = (error) => {
                 console.error("Offscreen: FileReader error:", error);
                 reject(new Error("Failed to convert cropped blob to data URL"));
            };
            reader.readAsDataURL(croppedBlob);
        });

    } catch (error) {
        console.error("Offscreen: Error during image processing:", error);
        throw error; // Re-throw to be caught by the caller
    }
}

console.log("Offscreen script loaded."); 