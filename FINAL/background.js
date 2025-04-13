// background.js

const NATIVE_HOST_NAME = "com.bomboclatt.ai_tutor_host"; // Ensure this matches manifest name
let nativePort = null;
let offscreenDocumentPath = 'offscreen.html';

// --- State Tracking ---
let isAiProcessing = false; 
let lastCroppedImageData = null;
let isExtensionOpen = false;

console.log("AI Tutor Background Script Loaded.");

// --- Native Messaging Handling ---

function connectNativeHost() {
    if (nativePort) {
        console.log("Native host already connected.");
        return true;
    }
    console.log(`Attempting to connect to native host: ${NATIVE_HOST_NAME}`);
    try {
        nativePort = chrome.runtime.connectNative(NATIVE_HOST_NAME);
        
        nativePort.onMessage.addListener((message) => {
            console.log("Received message from native host:", message);
            // Forward status to popup if needed
            chrome.runtime.sendMessage({type: "native_message", payload: message}).catch(() => {});
        });

        nativePort.onDisconnect.addListener(() => {
            const error = chrome.runtime.lastError;
            console.warn("Native host disconnected:", error?.message || "No error");
            
            // Only reset state if the extension is closed
            if (!isExtensionOpen) {
                isAiProcessing = false;
                lastCroppedImageData = null;
                nativePort = null;
            }
            
            // Notify popup of disconnect state
            chrome.runtime.sendMessage({
                type: "native_host_disconnected", 
                error: error?.message
            }).catch(() => {});
        });
        
        console.log("Native port event listeners added.");
        return true;
    } catch (e) {
        console.error(`Failed to connect to native host: ${e}`);
        handleConnectionError(e);
        return false;
    }
}

function disconnectNativeHost() {
    if (nativePort) {
        console.log("Disconnecting native host...");
        nativePort.disconnect();
        nativePort = null;
        isAiProcessing = false;
        lastCroppedImageData = null;
    }
}

function handleConnectionError(error) {
    isAiProcessing = false;
    chrome.notifications.create({
        type: 'basic',
        iconUrl: 'images/icon48.png',
        title: 'AI Tutor Connection Error',
        message: 'Could not connect to the backend application. Is it installed and registered correctly?'
    });
    chrome.runtime.sendMessage({
        type: "native_host_error", 
        error: error.message || "Connection failed"
    }).catch(() => {});
}

function sendToNativeHost(message) {
    if (!nativePort && !connectNativeHost()) {
        handleConnectionError(new Error("Cannot send message. Connection to backend failed."));
        return false;
    }
    
    try {
        console.log("Sending message to native host:", message.type);
        nativePort.postMessage(message);
        return true;
    } catch (e) {
        console.error("Error posting message to native host:", e);
        handleConnectionError(e);
        return false;
    }
}

// --- Connection Management ---
chrome.runtime.onConnect.addListener((port) => {
    if (port.name === 'popup') {
        console.log("Popup connected");
        isExtensionOpen = true;
        
        port.onDisconnect.addListener(() => {
            console.log("Popup disconnected");
            isExtensionOpen = false;
            
            // Only disconnect native host if AI is not processing
            if (!isAiProcessing) {
                disconnectNativeHost();
            }
        });
    }
});

// --- Offscreen Document Setup ---
async function hasOffscreenDocument(path) {
  // Check all windows controlled by the service worker to see if one 
  // contains the given path
  const offscreenUrl = chrome.runtime.getURL(path);
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT'],
    documentUrls: [offscreenUrl]
  });
  return contexts.length > 0;
}

async function setupOffscreenDocument(path) {
  if (await hasOffscreenDocument(path)) {
    console.log("Offscreen document already exists.");
  } else {
    console.log("Creating offscreen document...");
    await chrome.offscreen.createDocument({
      url: path,
      reasons: ['BLOBS'], // Or other appropriate reasons like DOM_PARSER if needed
      justification: 'Used for cropping screenshot image data',
    });
    console.log("Offscreen document created.");
  }
}

// Ensure offscreen document is ready when needed
async function ensureOffscreenDocument() {
    await setupOffscreenDocument(offscreenDocumentPath);
}

// --- Message Handling ---
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    console.log("Background: Message received:", request.type);

    switch (request.type) {
        case "start_screenshot":
            handleStartScreenshot(sender, sendResponse);
            return true;

        case "capture_area":
            handleCaptureArea(request, sender, sendResponse);
            return true;

        case "mute_mic":
        case "unmute_mic":
        case "interrupt_playback":  // Add handling for interrupt_playback
            console.log(`Background: Forwarding ${request.type} to native host.`);
            sendToNativeHost({ type: request.type });
            sendResponse({ success: true });
            return false;

        case "stop_native_host":
            console.log("Background: Received stop_native_host request.");
            disconnectNativeHost();
            sendResponse({ success: true });
            return false;

        case "reset_state":
            console.log("Background: Resetting state for next question.");
            isAiProcessing = false;
            lastCroppedImageData = null;
            // Don't disconnect native host
            sendResponse({ success: true });
            return false;

        case "reconnect_native_host":
            console.log("Background: Attempting to reconnect native host.");
            const success = connectNativeHost();
            sendResponse({ success });
            return false;

        case "get_status":
            console.log("Background: Received get_status request.");
            sendResponse({
                isProcessing: isAiProcessing,
                lastImageData: lastCroppedImageData,
                isConnected: nativePort !== null
            });
            return false;
    }
    
    return false;
});

async function handleStartScreenshot(sender, sendResponse) {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (tabs.length === 0) {
            console.error("Background: No active tab found.");
            sendResponse({ success: false, error: "No active tab" });
            return;
        }
        const activeTab = tabs[0];

        if (!activeTab.url || activeTab.url.startsWith('chrome://') || activeTab.url.startsWith('https://chrome.google.com/webstore/')) {
            console.warn(`Background: Cannot inject script into restricted URL: ${activeTab.url}`);
            chrome.notifications.create({
                type: 'basic',
                iconUrl: 'images/icon48.png',
                title: 'AI Tutor Warning',
                message: 'Cannot activate on this page (e.g., chrome:// or Web Store pages).'
            });
            sendResponse({ success: false, error: "Restricted URL" });
            return;
        }

        // Ensure native host connection before starting screenshot
        if (!nativePort && !connectNativeHost()) {
            sendResponse({ success: false, error: "Failed to connect to native host" });
            return;
        }

        console.log(`Background: Injecting content script into tab ${activeTab.id}`);
        chrome.scripting.executeScript({
            target: { tabId: activeTab.id },
            files: ['content_script.js']
        }, (injectionResults) => {
            if (chrome.runtime.lastError) {
                console.error(`Background: Script injection failed: ${chrome.runtime.lastError.message}`);
                sendResponse({ success: false, error: chrome.runtime.lastError.message });
            } else if (injectionResults && injectionResults.length > 0) {
                console.log("Background: content_script.js injected successfully.");
                chrome.scripting.insertCSS({
                    target: { tabId: activeTab.id },
                    files: ['style.css']
                }, () => { /* Ignore CSS injection errors */ });
                sendResponse({ success: true });
            } else {
                console.warn("Background: Script injection completed but no results returned.");
                sendResponse({ success: false, error: "Injection failed silently" });
            }
        });
    });
}

async function handleCaptureArea(request, sender, sendResponse) {
    console.log("Background: Received capture_area request with rect:", request.rect);
    const targetRect = request.rect;
    const dpr = request.dpr || 1; // Get DPR from the message
    
    // Need sender.tab.id to capture the correct tab
    if (!sender.tab || !sender.tab.id) {
        console.error("Background: Capture request received without sender tab ID.");
        sendResponse({ success: false, error: "Missing sender tab ID"});
        return true;
    }
    const targetTabId = sender.tab.id;
    
    // Ensure the offscreen document is ready for cropping
    ensureOffscreenDocument().then(() => {
        // Capture the visible tab content
        chrome.tabs.captureVisibleTab(sender.tab.windowId, { format: "png" }, (dataUrl) => {
            if (chrome.runtime.lastError) {
                console.error("Background: Error capturing visible tab:", chrome.runtime.lastError.message);
                sendResponse({ success: false, error: chrome.runtime.lastError.message });
                return;
            }
            if (!dataUrl) {
                console.error("Background: captureVisibleTab returned no dataUrl.");
                sendResponse({ success: false, error: "Failed to capture screenshot (no data)." });
                return;
            }
            console.log("Background: Full screenshot captured.");

            // Send full data URL, rect, and DPR to offscreen document
            chrome.runtime.sendMessage({
                type: "crop_image",
                target: "offscreen",
                dataUrl: dataUrl,
                rect: targetRect,
                dpr: dpr // Pass DPR along
            }, (response) => {
                if (chrome.runtime.lastError) {
                     console.error("Background: Error sending message to offscreen doc:", chrome.runtime.lastError.message);
                     sendResponse({ success: false, error: `Offscreen messaging error: ${chrome.runtime.lastError.message}`});
                     return;
                }
                
                if (response && response.success && response.croppedDataUrl) {
                    console.log("Background: Received cropped image from offscreen doc.");
                    lastCroppedImageData = response.croppedDataUrl; // Store for popup state
                    
                    // Notify popup that screenshot is taken and processing started
                    chrome.runtime.sendMessage({
                        type: "screenshot_taken", 
                        imageData: lastCroppedImageData
                    }).catch(e => console.warn("Popup not open when sending screenshot?"));

                    // Connect and send to native host
                    connectNativeHost(); // Ensure connected
                    if(nativePort) { // Check connection success before sending
                        sendToNativeHost({
                            type: "image_data",
                            imageData: lastCroppedImageData // Send base64 data URL
                        });
                        isAiProcessing = true; // Mark as processing
                        sendResponse({ success: true, message: "Image sent to host" });
                    } else {
                        // Connection failed in connectNativeHost(), error already handled/notified
                         isAiProcessing = false;
                         sendResponse({ success: false, error: "Failed to connect to native host."});
                    }
                } else {
                    console.error("Background: Failed to get cropped image from offscreen doc.", response);
                    isAiProcessing = false;
                    lastCroppedImageData = null;
                    sendResponse({ success: false, error: response?.error || "Cropping failed" });
                }
            });
        });
    }).catch(error => {
        console.error("Background: Error ensuring offscreen document:", error);
        isAiProcessing = false;
        lastCroppedImageData = null;
        sendResponse({ success: false, error: "Failed to setup cropping environment" });
    });

    return true; // Indicate async response
}

console.log("AI Tutor: Background script loaded.");