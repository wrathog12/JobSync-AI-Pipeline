1. System Architecture OverviewThe system strictly decouples the Context Acquisition/Injection Layer (Chrome Extension) from the Inference and Processing Layer (FastAPI/Node Backend) to bypass Chrome’s Manifest V3 execution limits and SPA cross-origin restrictions.Client (Manifest V3 Chrome Extension): Operates on the DOM via content_scripts. It maps field schemas, observes dynamic React/Angular mutations, and performs direct native DOM property descriptor overrides.Server (FastAPI / Next.js): Maintains the inference pipeline. It orchestrates the LLM context limits, schema validations, unstructured HTML parsing via Retrieval-Augmented Generation (RAG) (if a JD is provided), and automated LaTeX subprocess executions.2. Chrome Extension: Data Acquisition & State MappingYou cannot parse React’s Virtual DOM directly. The extension must traverse the physical browser DOM to extract labels and metadata.Target Mapping and Unique IdentifiersWhen the extension initializes on a job board (e.g., *.greenhouse.io, *.workday.com), a MutationObserver watches the document.body for added <input>, <textarea>, and select nodes.Instantiation: As each interactive node enters the DOM, it is assigned a cryptographic UUID or high-entropy hash (let fieldId = crypto.randomUUID();).Memory Map Registration: The physical DOM node reference is stored in an ephemeral WeakMap or standard Map tied to the window context: DOMRegistry.set(fieldId, targetNode);.Context Traversal:Attribute Lookups: node.getAttribute('aria-label') or node.name.Relational Lookups: Locate <label for="[node.id]"> and extract innerText.Ancestor Traversals: If orphaned, the script traverses up using node.closest('div, label, fieldset') to extract bounding text content.Constraint Extraction AlgorithmBefore dispatching the payload, the client extracts implicit and explicit constraints:Explicit HTML Limits: Query node.maxLength. If the value is -1 or 524288 (default unconstrained), fallback to regex.Implicit Limits (Regex Parsing): Search node.placeholder and nearest sibling spans/paragraphs using regex:JavaScriptconst limitRegex = /(?:max(?:imum)?\s*)?(\d+)\s*(?:chars?|characters?|words?)/i;
Enums/Dropdowns: For <select>, map all child <option> strings into an array. For React custom <div> dropdowns, the scraper must listen for role="listbox" or role="option" elements.Outbound Payload Structure:JSON{
  "page_url": "https://boards.greenhouse.io/...",
  "job_description_raw": "...", // document.querySelector('.job-description').innerText
  "fields": [
    {
      "id": "e4b3-4f9a...",
      "type": "textarea",
      "context_label": "What is your biggest weakness?",
      "constraints": {
        "max_chars": 500,
        "is_required": true
      }
    }
  ]
}
3. The React SPA Injection Bypass (Minute Details)React (and Angular) intercepts DOM events and maintains an internal state tree. Assigning node.value = "text" updates the browser UI but leaves the React state empty, causing validation to fail on submission.The Native Prototype Override MethodTo bypass React's custom setter, the content script must grab the native HTMLInputElement or HTMLTextAreaElement prototype descriptor, force the value, and dispatch a bubbling event:  JavaScriptfunction injectBypassingReact(node, payloadText) {
    // 1. Determine the prototype based on node type
    const prototype = Object.getPrototypeOf(node);
    
    // 2. Extract the native property setter, skipping React's monkey-patched setter
    const nativeSetter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
    
    // 3. Force the value natively
    nativeSetter.call(node, payloadText);
    
    // 4. Dispatch synthetic events to force a React re-render/state sync
    node.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    node.dispatchEvent(new Event('change', { bubbles: true }));
}
The Nuclear Option: chrome.debugger ProtocolIf enterprise platforms (e.g., Workday iFrames) use aggressive bot-detection scripts that block synthetic events, the fallback is the Chrome DevTools Protocol (CDP) via the chrome.debugger API.  This bypasses JavaScript entirely and communicates directly with the Chromium browser process to simulate hardware-level keystrokes:  JavaScriptchrome.debugger.sendCommand(
    { targetId: targetId },
    "Input.insertText",
    { text: payloadText }
);
Note: This requires the "debugger" permission in manifest.json and will display an active debugging banner to the user.4. Backend Inference & LLM HandlingWhen the FastAPI server receives the JSON array, it passes the data to the LLM agent via strict structured outputs (JSON schema constraints via OpenAI or Gemini API).Handling the Character Limit Trap:LLMs tokenize words (where 1 token ≈ 4 chars), meaning they struggle with strict character limits. The backend must enforce a mathematical buffer dynamically injected into the system prompt:Algorithm: target_limit = max_chars * 0.8Prompt Injection: "CRITICAL CONSTRAINT: You must generate a response strictly under {target_limit} characters to satisfy a {max_chars} hard UI limit."The backend maps the generated answers back to their exact UUIDs and returns the resolved JSON object to the extension for the injectBypassingReact loop.5. LaTeX Subprocess ArchitectureFor the resume and cover letter generation module, the server must process JSON to PDF without allowing the AI to write .tex files natively, preventing syntax compilation crashes (e.g., unescaped % or &).Template Engine (Jinja2):Store a validated .tex document containing Jinja2 template tags (e.g., \textbf{ {{ job.title }} }).Crucial step: You must reconfigure Jinja2's default delimiters because LaTeX uses { and } heavily. Rebind Jinja2 blocks to <% %> or [[ ]] to avoid collision with LaTeX commands.Data Sanitization:A Python middleware script loops through the AI-generated JSON strings and escapes LaTeX-specific characters before injection: string.replace("&", r"\&").replace("%", r"\%").Compilation (Subprocess):Save the injected template to a temporary directory (/tmp/resume_session.tex). Execute the pdflatex or xelatex compiler via Python's subprocess:Pythonimport subprocess

process = subprocess.run(
    ["pdflatex", "-interaction=nonstopmode", "-output-directory=/tmp", "/tmp/resume_session.tex"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)
Buffer Delivery:The resulting /tmp/resume_session.pdf is read into memory, converted to a base64 buffer or streamed back via HTTP chunking to the Chrome extension for immediate download.