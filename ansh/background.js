// background.js

const NATIVE_HOST_NAME = "com.bomboclatt.ai_tutor_host"; // Ensure this matches manifest name
let nativePort = null;
let offscreenDocumentPath = 'offscreen.html';

// --- State Tracking ---
let isAiProcessing = false; 
let lastCroppedImageData = null;

console.log("AI Tutor Background Script Loaded.");

// --- Native Messaging Handling ---

function connectNativeHost() {
    if (nativePort) {
        console.log("Native host already connected.");
        return;
    }
    console.log(`Attempting to connect to native host: ${NATIVE_HOST_NAME}`);
    try {
        nativePort = chrome.runtime.connectNative(NATIVE_HOST_NAME);
        isAiProcessing = true; // Assume processing starts on connection

        nativePort.onMessage.addListener((message) => {
            console.log("Received message from native host:", message);
            // Example: Forward status to popup if needed
            // chrome.runtime.sendMessage({type: "native_message", payload: message});
        });

        nativePort.onDisconnect.addListener(() => {
            isAiProcessing = false; // Processing stops on disconnect
            lastCroppedImageData = null; // Clear last image on disconnect
            let errorMsg = "Native host disconnected.";
            if (chrome.runtime.lastError) {
                errorMsg = `Native host disconnected with error: ${chrome.runtime.lastError.message}`;
                console.error(errorMsg);
                 // Notify popup of error
                 chrome.runtime.sendMessage({type: "native_host_error", error: chrome.runtime.lastError.message}).catch(e => console.warn("Popup not open?"));
            } else {
                console.log(errorMsg);
                // Notify popup of disconnect
                chrome.runtime.sendMessage({type: "native_host_disconnected"}).catch(e => console.warn("Popup not open?"));
            }
            nativePort = null;
        });
        console.log("Native port event listeners added.");
    } catch (e) {
        console.error(`Failed to connect to native host: ${e}`);
        isAiProcessing = false;
        chrome.notifications.create({
             type: 'basic',
             iconUrl: 'images/icon48.png',
             title: 'AI Tutor Connection Error',
             message: 'Could not connect to the backend application. Is it installed and registered correctly?'
         });
         chrome.runtime.sendMessage({type: "native_host_error", error: e.message || "Connection failed"}).catch(err => console.warn("Popup not open?"));
    }
}

function disconnectNativeHost() {
    if (nativePort) {
        console.log("Disconnecting native host...");
        nativePort.disconnect();
        // onDisconnect listener handles setting nativePort = null and isAiProcessing = false
    }
}

function sendToNativeHost(message) {
    if (!nativePort) {
        console.error("Error sending message: Native host not connected.");
        isAiProcessing = false; // Ensure state reflects reality
        chrome.runtime.sendMessage({type: "native_host_error", error: "Not connected"}).catch(e => console.warn("Popup not open?"));
        // Optionally try to connect here? For now, assume connection fails.
        chrome.notifications.create({
             type: 'basic',
             iconUrl: 'images/icon48.png',
             title: 'AI Tutor Connection Error',
             message: 'Cannot send message. Connection to backend lost.'
         });
        return;
    }
    try {
        console.log("Sending message to native host:", message.type);
        nativePort.postMessage(message);
    } catch (e) {
        console.error("Error posting message to native host:", e);
        if (nativePort) {
            nativePort.disconnect(); // Trigger disconnect logic
        }
        nativePort = null; // Explicitly nullify
        isAiProcessing = false;
        chrome.runtime.sendMessage({type: "native_host_error", error: e.message || "Send failed"}).catch(err => console.warn("Popup not open?"));
    }
}

// Attempt initial connection (optional, can connect on first message)
// connectNativeHost();

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

    if (request.type === "start_screenshot") {
        console.log("Background: Received start_screenshot request from popup.");
        // Get the current active tab to inject the content script
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
            if (tabs.length === 0) {
                console.error("Background: No active tab found.");
                sendResponse({ success: false, error: "No active tab" });
                return;
            }
            const activeTab = tabs[0];

            // Check for restricted URLs before injecting
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
                    }, () => { /* Ignore CSS injection errors for now */ });
                    sendResponse({ success: true, message: "Injection started" });
                 } else {
                     console.warn("Background: Script injection completed but no results returned.");
                     sendResponse({ success: false, error: "Injection failed silently" });
                 }
            });
        });
        return true; // Indicate async response

    } else if (request.type === "capture_area") {
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
    
    // --- New message handlers ---
    } else if (request.type === "stop_native_host") {
        console.log("Background: Received stop_native_host request.");
        disconnectNativeHost();
        isAiProcessing = false;
        lastCroppedImageData = null;
        sendResponse({ success: true });
        return false; // Synchronous response OK

    } else if (request.type === "get_status") {
        console.log("Background: Received get_status request.");
        sendResponse({
             isProcessing: isAiProcessing,
             lastImageData: lastCroppedImageData
        });
        return false; // Synchronous response OK
    }
    
    return false; // Default sync response for unhandled types
});

// --- Add listener for when native host disconnects unexpectedly ---
// (Handled within the onDisconnect listener setup in connectNativeHost)

// --- Initial setup on extension start (optional) ---
// console.log("AI Tutor: Background script initial setup.");

// --- Cleanup on shutdown? (Less critical for service workers) ---
// chrome.runtime.onSuspend.addListener(() => {
//     console.log("Background: Suspending. Disconnecting native host if connected.");
//     disconnectNativeHost();
// });

console.log("AI Tutor: Background script loaded."); 