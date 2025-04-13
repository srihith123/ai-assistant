// content_script.js

(function() {
    // Prevent multiple instances
    if (window.aiTutorActive) {
        console.log("AI Tutor overlay already active.");
        return;
    }
    window.aiTutorActive = true;

    let startX, startY, selectionBox;
    let isDrawing = false;

    const overlay = document.createElement('div');
    overlay.id = 'ai-tutor-overlay';
    document.body.appendChild(overlay);

    selectionBox = document.createElement('div');
    selectionBox.id = 'ai-tutor-selection-box';
    document.body.appendChild(selectionBox);

    overlay.addEventListener('mousedown', handleMouseDown);
    overlay.addEventListener('mousemove', handleMouseMove);
    overlay.addEventListener('mouseup', handleMouseUp);
    document.addEventListener('keydown', escapeListener); // Add escape listener

    console.log("AI Tutor: Overlay added. Draw a box.");

    function handleMouseDown(e) {
        e.preventDefault();
        isDrawing = true;
        startX = e.clientX;
        startY = e.clientY;
        selectionBox.style.left = `${startX}px`;
        selectionBox.style.top = `${startY}px`;
        selectionBox.style.width = '0px';
        selectionBox.style.height = '0px';
        selectionBox.style.display = 'block';
    }

    function handleMouseMove(e) {
        if (!isDrawing) return;
        const currentX = e.clientX;
        const currentY = e.clientY;
        const width = Math.abs(currentX - startX);
        const height = Math.abs(currentY - startY);
        const left = Math.min(currentX, startX);
        const top = Math.min(currentY, startY);
        selectionBox.style.left = `${left}px`;
        selectionBox.style.top = `${top}px`;
        selectionBox.style.width = `${width}px`;
        selectionBox.style.height = `${height}px`;
    }

    function handleMouseUp(e) {
        if (!isDrawing) return;
        isDrawing = false;

        // Get coordinates relative to the viewport
        const viewportX = parseInt(selectionBox.style.left, 10);
        const viewportY = parseInt(selectionBox.style.top, 10);
        const width = parseInt(selectionBox.style.width, 10);
        const height = parseInt(selectionBox.style.height, 10);

        // Adjust coordinates by scroll offset to get document-relative coordinates
        const finalRect = {
            x: viewportX + window.scrollX,
            y: viewportY + window.scrollY,
            width: width,
            height: height
        };

        // Clean up UI immediately
        cleanup(); 

        // Only send coordinates if the box has a reasonable size
        if (finalRect.width > 5 && finalRect.height > 5) {
            const dpr = window.devicePixelRatio || 1;
            console.log(`AI Tutor: Selected area - x: ${finalRect.x}, y: ${finalRect.y}, width: ${finalRect.width}, height: ${finalRect.height}, dpr: ${dpr}`);
            // Send coordinates and DPR to the background script
            chrome.runtime.sendMessage({ 
                type: "capture_area", 
                rect: finalRect, 
                dpr: dpr 
            }, (response) => {
                if (chrome.runtime.lastError) {
                    console.error("AI Tutor Error sending coordinates:", chrome.runtime.lastError.message);
                    // Handle error if needed
                } else {
                    console.log("AI Tutor: Coordinates sent to background.", response);
                }
            });
        } else {
            console.log("AI Tutor: Selection too small, cancelling.");
        }
    }

    function escapeListener(e) {
        if (e.key === 'Escape') {
            console.log("AI Tutor: Escape key pressed, cleaning up.");
            cleanup();
        }
    }

    function cleanup() {
        console.log("AI Tutor: Cleaning up overlay and selection box.");
        window.aiTutorActive = false; // Reset flag
        if (overlay) {
            overlay.removeEventListener('mousedown', handleMouseDown);
            overlay.removeEventListener('mousemove', handleMouseMove);
            overlay.removeEventListener('mouseup', handleMouseUp);
            if(overlay.parentNode) overlay.parentNode.removeChild(overlay);
        }
        if (selectionBox) {
             if(selectionBox.parentNode) selectionBox.parentNode.removeChild(selectionBox);
        }
        document.removeEventListener('keydown', escapeListener); // Remove listener
        // Allow garbage collection
        selectionBox = null; 
    }

    // Add a listener for messages from background (e.g., to re-activate or ping)
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (request.type === "ping") {
             console.log("AI Tutor Content Script: Ping received");
             sendResponse({ status: "pong" });
             return true;
        } else if (request.type === "activate") {
            // This could potentially re-show UI if it was hidden instead of removed
             console.log("AI Tutor Content Script: Activate request received (no action defined)");
             sendResponse({ status: "activated_noop" });
             return true;
        }
        return false;
    });

})(); // IIFE 