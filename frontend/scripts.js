const GPTResearcher = (() => {
  let isResearchActive = false;
  let connectionTimeout = null;
  let conversationHistory = [];
  let isInitialLoad = true; // Flag to track initial page load
  let cookiesEnabled = true; // Flag to track if cookies are enabled
  let allReports = ''; // Store all reports cumulatively
  let currentReport = ''; // Store the current report (will be overwritten)
  let isFirstReport = true; // Flag to track if this is the first report
  let chatContainer = null; // Global reference to chat container
  let lastRequestData = null; // Store the last request data for reconnection

  // Add WebSocket monitoring variables
  let socket = null;
  let connectionStartTime = null;
  let lastActivityTime = null;
  let connectionAttempts = 0;
  let messagesReceived = 0;
  let websocketMonitorInterval = null;
  let dispose_socket = null; // Re-add dispose_socket
  let reconnectAttempts = 0;
  let maxReconnectAttempts = 5;
  let reconnectInterval = 2000; // Start with 2 seconds

  const init = () => {
    // Check if cookies are enabled
    checkCookiesEnabled();

    // Load history immediately on page load
    loadConversationHistory();

    // After a short delay, mark initial load as complete
    setTimeout(() => {
      isInitialLoad = false;
    }, 1000);

    // Setup form submission
    // 注意：下面两处查找必须保持「有则绑定、无则跳过」。
    // 之前是无保护的 getElementById(...).addEventListener(...)，
    // 一旦对应元素不存在就会抛错，导致 init() 中断、整页 JS 全部失效。
    const researchForm = document.getElementById('researchForm');
    if (researchForm) {
      researchForm.addEventListener('submit', (e) => {
        e.preventDefault();
        startResearch();
        return false;
      });
    }

    const bottomCopyButton = document.getElementById('copyToClipboard');
    if (bottomCopyButton) {
      bottomCopyButton.addEventListener('click', copyToClipboard);
    }

    // Add event listener for the top copy button
    const topCopyButton = document.getElementById('copyToClipboardTop');
    if (topCopyButton) {
      topCopyButton.addEventListener('click', copyToClipboard);
    }

    // Initialize expand buttons
    initExpandButtons();

    // Initialize history panel functionality
    initHistoryPanel();

    // Initialize WebSocket monitoring panel
    initWebSocketPanel();

    // Initialize MCP functionality
    initMCPSection();

    // The download bar is now fixed in place with CSS
    // No need to set display property here

    updateState('initial');

    // Initialize research icon to not spinning
    updateResearchIcon(false);
  }

  // Check if cookies are enabled
  const checkCookiesEnabled = () => {
    try {
      // Try to set a test cookie
      document.cookie = "testcookie=1; path=/";
      const cookieEnabled = document.cookie.indexOf("testcookie") !== -1;

      if (!cookieEnabled) {
        console.warn("Cookies are disabled in this browser");
        cookiesEnabled = false;
        showToast("浏览器已禁用 Cookie，历史记录将改用 localStorage 存储。", 5000);
      } else {
        // Clean up test cookie
        document.cookie = "testcookie=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
        cookiesEnabled = true;
      }

      return cookieEnabled;
    } catch (e) {
      console.error("Error checking cookies:", e);
      cookiesEnabled = false;
      return false;
    }
  }

  // Initialize conversation history panel functionality
  const initHistoryPanel = () => {
    // Load history from cookie
    loadConversationHistory();

    // Setup history panel toggle button
    const historyPanelOpenBtn = document.getElementById('historyPanelOpenBtn');
    const historyPanel = document.getElementById('historyPanel');
    const historyPanelToggle = document.getElementById('historyPanelToggle');

    if (historyPanelOpenBtn) {
      historyPanelOpenBtn.addEventListener('click', () => {
        loadConversationHistory(); // Reload history when opening panel
        historyPanel.classList.add('open');
      });
    }

    if (historyPanelToggle) {
      historyPanelToggle.addEventListener('click', () => {
        historyPanel.classList.remove('open');
      });
    }

    // Close panel when clicking outside
    document.addEventListener('click', (e) => {
      // If the panel is open and the click is outside the panel and not on the toggle button
      if (historyPanel.classList.contains('open') &&
        !historyPanel.contains(e.target) &&
        e.target !== historyPanelOpenBtn &&
        !historyPanelOpenBtn.contains(e.target)) {
        historyPanel.classList.remove('open');
      }
    });

    // Setup search functionality
    const historySearch = document.getElementById('historySearch');
    const historySearchBtn = document.getElementById('historySearchBtn');

    if (historySearch && historySearchBtn) {
      historySearch.addEventListener('input', filterHistoryEntries);
      historySearchBtn.addEventListener('click', () => filterHistoryEntries());
    }

    // Setup sort functionality
    const historySortOrder = document.getElementById('historySortOrder');
    if (historySortOrder) {
      historySortOrder.addEventListener('change', () => {
        sortHistoryEntries(historySortOrder.value);
        renderHistoryEntries();
      });
    }

    // Setup clear history button
    const historyClearBtn = document.getElementById('historyClearBtn');
    if (historyClearBtn) {
      historyClearBtn.addEventListener('click', clearConversationHistory);
    }

    // Add action buttons to history panel
    const historyFilters = document.querySelector('.history-panel-filters');
    if (historyFilters) {
      // Create a container for the buttons
      const actionsContainer = document.createElement('div');
      actionsContainer.className = 'history-actions-container';

      // Add export history button with enhanced styling and tooltip
      const exportBtn = document.createElement('button');
      exportBtn.className = 'history-action-btn';
      exportBtn.title = '导出研究历史到文件';
      exportBtn.innerHTML = '<i class="fas fa-file-export"></i>';
      exportBtn.addEventListener('click', exportHistory);

      // Add import history button with enhanced styling and tooltip
      const importBtn = document.createElement('button');
      importBtn.className = 'history-action-btn';
      importBtn.title = '从文件导入研究历史';
      importBtn.innerHTML = '<i class="fas fa-file-import"></i>';
      importBtn.addEventListener('click', triggerImportHistory);

      // Add cookie debug button with enhanced styling and tooltip
      const debugBtn = document.createElement('button');
      debugBtn.className = 'history-action-btn';
      debugBtn.title = '检查存储状态';
      debugBtn.innerHTML = '<i class="fas fa-database"></i>';
      debugBtn.addEventListener('click', checkCookieStatus);

      // Add buttons to container in a logical order
      actionsContainer.appendChild(importBtn);
      actionsContainer.appendChild(exportBtn);
      actionsContainer.appendChild(debugBtn);

      // Create a hidden file input for importing
      const fileInput = document.createElement('input');
      fileInput.type = 'file';
      fileInput.id = 'historyFileInput';
      fileInput.accept = '.json';
      fileInput.style.display = 'none';
      fileInput.addEventListener('change', handleFileImport);

      // Add container and file input to filters
      historyFilters.appendChild(actionsContainer);
      historyFilters.appendChild(fileInput);
    }

    // Initial render of history entries
    renderHistoryEntries();
  }

  // Initialize WebSocket monitoring panel
  const initWebSocketPanel = () => {
    const websocketPanel = document.getElementById('websocketPanel');
    const websocketPanelOpenBtn = document.getElementById('websocketPanelOpenBtn');
    const websocketPanelToggle = document.getElementById('websocketPanelToggle');

    if (!websocketPanel || !websocketPanelOpenBtn || !websocketPanelToggle) {
      console.error("WebSocket panel elements not found");
      return;
    }

    console.log("Initializing WebSocket panel");

    // Ensure it starts hidden
    websocketPanel.classList.remove('open');

    websocketPanelOpenBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      console.log("Opening WebSocket panel");
      websocketPanel.classList.add('open');
    });

    websocketPanelToggle.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      console.log("Closing WebSocket panel");
      websocketPanel.classList.remove('open');
    });

    // Close panel when clicking outside
    document.addEventListener('click', (e) => {
      // If the panel is open and the click is outside the panel and not on the toggle button
      if (websocketPanel.classList.contains('open') &&
        !websocketPanel.contains(e.target) &&
        e.target !== websocketPanelOpenBtn &&
        !websocketPanelOpenBtn.contains(e.target)) {
        websocketPanel.classList.remove('open');
      }
    });

    // Start periodic WebSocket status updates
    startWebSocketMonitoring();
  }

  // Start WebSocket monitoring
  const startWebSocketMonitoring = () => {
    console.log("Starting WebSocket monitoring");

    // Update status immediately
    updateWebSocketStatus();

    // Clear any existing interval
    if (websocketMonitorInterval) {
      clearInterval(websocketMonitorInterval);
    }

    // Update status every 2 seconds
    websocketMonitorInterval = setInterval(updateWebSocketStatus, 2000);
  }

  // Update WebSocket status in the panel
  const updateWebSocketStatus = () => {
    // Only proceed if the necessary elements exist
    const connectionStatusEl = document.getElementById('connectionStatus');
    const connectionIndicatorEl = document.getElementById('connectionIndicator');
    const researchStatusEl = document.getElementById('researchStatus');
    const connectionDurationEl = document.getElementById('connectionDuration');
    const lastActivityEl = document.getElementById('lastActivity');
    const readyStateEl = document.getElementById('readyState');
    const connectionAttemptsEl = document.getElementById('connectionAttempts');
    const messagesReceivedEl = document.getElementById('messagesReceived');
    const currentTaskEl = document.getElementById('currentTask');

    if (!connectionStatusEl || !connectionIndicatorEl) return;

    // Update connection status
    const socketStatus = getSocketStatus();
    connectionStatusEl.textContent = socketStatus.statusText;

    // Update indicator class
    connectionIndicatorEl.className = 'status-indicator';
    connectionIndicatorEl.classList.add(socketStatus.indicatorClass);

    // Update research status
    if (researchStatusEl) {
      researchStatusEl.textContent = isResearchActive ? '进行中' : '空闲';
    }

    // Update connection duration
    if (connectionDurationEl && connectionStartTime) {
      const duration = Math.floor((Date.now() - connectionStartTime) / 1000);
      connectionDurationEl.textContent = formatDuration(duration);
    } else if (connectionDurationEl) {
      connectionDurationEl.textContent = '-';
    }

    // Update last activity
    if (lastActivityEl && lastActivityTime) {
      const elapsed = Math.floor((Date.now() - lastActivityTime) / 1000);
      lastActivityEl.textContent = elapsed < 60 ? `${elapsed} 秒前` : formatDuration(elapsed) + '前';
    } else if (lastActivityEl) {
      lastActivityEl.textContent = '-';
    }

    // Update ReadyState
    if (readyStateEl && socket) {
      readyStateEl.textContent = getReadyStateText(socket.readyState);
    } else if (readyStateEl) {
      readyStateEl.textContent = '-';
    }

    // Update connection attempts
    if (connectionAttemptsEl) {
      connectionAttemptsEl.textContent = connectionAttempts.toString();
    }

    // Update messages received
    if (messagesReceivedEl) {
      messagesReceivedEl.textContent = messagesReceived.toString();
    }

    // Update current task
    if (currentTaskEl) {
      const taskInput = document.getElementById('task');
      currentTaskEl.textContent = isResearchActive && taskInput && taskInput.value ?
        (taskInput.value.length > 30 ? taskInput.value.substring(0, 27) + '...' : taskInput.value) :
        '-';
    }
  }

  // Get socket status object
  const getSocketStatus = () => {
    if (!socket) {
      return {
        statusText: '未连接',
        indicatorClass: 'disconnected'
      };
    }

    switch (socket.readyState) {
      case WebSocket.CONNECTING:
        return {
          statusText: '连接中',
          indicatorClass: 'connecting'
        };
      case WebSocket.OPEN:
        return {
          statusText: '已连接',
          indicatorClass: 'connected'
        };
      case WebSocket.CLOSING:
        return {
          statusText: '关闭中',
          indicatorClass: 'connecting'
        };
      case WebSocket.CLOSED:
      default:
        return {
          statusText: '未连接',
          indicatorClass: 'disconnected'
        };
    }
  }

  // Get readable text for WebSocket readyState
  const getReadyStateText = (readyState) => {
    switch (readyState) {
      case WebSocket.CONNECTING:
        return '0（连接中）';
      case WebSocket.OPEN:
        return '1（已打开）';
      case WebSocket.CLOSING:
        return '2（关闭中）';
      case WebSocket.CLOSED:
        return '3（已关闭）';
      default:
        return `${readyState}（未知）`;
    }
  }

  // Format duration in seconds to human-readable string
  const formatDuration = (seconds) => {
    if (seconds < 60) {
      return `${seconds} 秒`;
    } else if (seconds < 3600) {
      return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
    } else {
      const hours = Math.floor(seconds / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      return `${hours} 小时 ${minutes} 分`;
    }
  }

  // Load conversation history from cookie
  const loadConversationHistory = () => {
    try {
      const storedHistory = getCookie('conversationHistory');
      if (storedHistory && storedHistory.trim() !== '') {
        try {
          const parsedHistory = JSON.parse(storedHistory);
          if (Array.isArray(parsedHistory)) {
            conversationHistory = parsedHistory;
            console.debug('Loaded research history from storage:', conversationHistory);
            console.log('Loaded research history:', conversationHistory.length, 'items');
          } else {
            console.warn('History storage does not contain an array');
            conversationHistory = [];
            deleteCookie('conversationHistory');
          }
        } catch (jsonError) {
          console.error('Invalid JSON in history storage:', jsonError);
          conversationHistory = [];
          deleteCookie('conversationHistory');
        }
      } else {
        console.log('No research history found in storage');
        conversationHistory = [];
      }
    } catch (error) {
      console.error('Error loading research history from storage:', error);
      conversationHistory = [];
      // If JSON parsing fails, delete the corrupt cookie
      deleteCookie('conversationHistory');
    }

    // Force render after loading
    renderHistoryEntries();
  }

  // Save conversation history to cookie
  const saveConversationHistory = () => {
    try {
      if (conversationHistory.length === 0) {
        deleteCookie('conversationHistory');
        console.debug('No history to save, deleted storage');
        return;
      }

      // Only keep the last 20 entries
      let storageHistory = [...conversationHistory];
      if (storageHistory.length > 20) {
        storageHistory = storageHistory.slice(0, 20);
        console.debug('Trimmed history to last 20 entries');
      }

      // Only keep minimal fields: prompt, links and timestamp
      storageHistory = storageHistory.map(entry => ({
        prompt: entry.prompt || '',
        links: entry.links || {},
        timestamp: entry.timestamp || new Date().toISOString()
      }));

      const jsonString = JSON.stringify(storageHistory);
      console.debug('History JSON size:', jsonString.length, 'characters');

      setCookie('conversationHistory', jsonString, 30);

      if (storageHistory.length > 0 && !isInitialLoad) {
        showToast('研究历史已保存！');
      }
    } catch (error) {
      console.error('Error saving research history:', error);
      showToast('保存历史失败，部分条目可能未保存。');
    }
  }

  // Delete a history entry
  const deleteHistoryEntry = (index) => {
    if (confirm('确定要删除这条研究记录吗？')) {
      conversationHistory.splice(index, 1);
      saveConversationHistory();
      renderHistoryEntries();
      showToast('条目已删除');
    }
  }

  // Clear all conversation history
  const clearConversationHistory = () => {
    if (confirm('确定要清空全部研究历史吗？此操作无法撤销。')) {
      conversationHistory = [];
      saveConversationHistory();
      renderHistoryEntries();
      showToast('研究历史已清空');
    }
  }

  // Filter history entries based on search term
  const filterHistoryEntries = () => {
    const searchTerm = document.getElementById('historySearch').value.toLowerCase();
    const historyEntries = document.getElementById('historyEntries');

    if (!historyEntries) return;

    const entries = historyEntries.querySelectorAll('.history-entry');

    entries.forEach(entry => {
      const title = entry.querySelector('.history-entry-title').textContent.toLowerCase();
      // Search only in the title since we no longer have preview text
      if (title.includes(searchTerm)) {
        entry.style.display = 'block';
      } else {
        entry.style.display = 'none';
      }
    });
  }

  // Sort history entries by timestamp
  const sortHistoryEntries = (order) => {
    conversationHistory.sort((a, b) => {
      // Default to newest first if timestamps don't exist
      if (!a.timestamp || !b.timestamp) return 0;

      if (order === 'newest') {
        return new Date(b.timestamp) - new Date(a.timestamp);
      } else {
        return new Date(a.timestamp) - new Date(b.timestamp);
      }
    });
  }

  // Render history entries in the panel
  const renderHistoryEntries = () => {
    const historyEntries = document.getElementById('historyEntries');
    if (!historyEntries) return;

    historyEntries.innerHTML = '';

    if (!conversationHistory || conversationHistory.length === 0) {
      historyEntries.innerHTML = '<p class="text-center mt-4 text-muted">还没有研究历史。</p>';
      return;
    }

    // Sort by the current selection
    const sortOrder = document.getElementById('historySortOrder')?.value || 'newest';
    sortHistoryEntries(sortOrder);
    console.debug('Sorted history entries:', sortOrder);

    conversationHistory.forEach((entry, index) => {
      const entryElement = document.createElement('div');
      entryElement.className = 'history-entry';
      entryElement.setAttribute('data-id', index);

      // Make the entire entry clickable to load it
      entryElement.addEventListener('click', () => {
        loadResearchEntry(index);
      });

      // Format timestamp if available
      let timestampHTML = '';
      if (entry.timestamp) {
        try {
          const timestamp = new Date(entry.timestamp);
          const formattedDate = timestamp.toLocaleDateString('zh-CN');
          const formattedTime = timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
          timestampHTML = `<span class="history-entry-timestamp">${formattedDate} ${formattedTime}</span>`;
        } catch (e) {
          console.error('Error formatting timestamp:', e);
        }
      }

      // Make sure links object exists
      const links = entry.links || {};

      // Build the HTML for the entry with enhanced formatting
      entryElement.innerHTML = `
        <div class="history-entry-header">
          <h4 class="history-entry-title">${entry.prompt || '未命名研究'}</h4>
          ${timestampHTML}
        </div>
        <div class="history-entry-format">
          ${links.docx ? `<a href="${links.docx}" class="history-entry-action" target="_blank" title="打开 Word 文档"><i class="fas fa-file-word"></i> Word</a>` : ''}
          ${links.md ? `<a href="${links.md}" class="history-entry-action" target="_blank" title="打开 Markdown 文件"><i class="fas fa-file-lines"></i> MD</a>` : ''}
          ${links.json ? `<a href="${links.json}" class="history-entry-action" target="_blank" title="打开 JSON 数据"><i class="fas fa-file-code"></i> JSON</a>` : ''}
        </div>
        <div class="history-entry-actions">
          <button class="history-entry-action delete-entry" title="删除这条研究记录"><i class="fas fa-trash-alt"></i></button>
        </div>
      `;

      // Add action button handlers
      const deleteBtn = entryElement.querySelector('.delete-entry');
      if (deleteBtn) {
        deleteBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          deleteHistoryEntry(index);
        });
      }

      historyEntries.appendChild(entryElement);
      setTimeout(() => {
        entryElement.style.animationDelay = `${index * 50}ms`;
      }, 0);
    });
  }

  // Load a research entry from history
  const loadResearchEntry = (index) => {
    const entry = conversationHistory[index];
    if (!entry) return;

    // Fill form with the entry data
    document.getElementById('task').value = entry.prompt; // Changed from entry.task for consistency
    
    // Check if report_type, report_source, and tone are in entry, otherwise use defaults or skip
    const reportTypeSelect = document.querySelector('select[name="report_type"]');
    if (reportTypeSelect && entry.reportType) {
        reportTypeSelect.value = entry.reportType;
    } else if (reportTypeSelect) {
        reportTypeSelect.value = reportTypeSelect.options[0].value; // Default to first option
    }

    const reportSourceSelect = document.querySelector('select[name="report_source"]');
    if (reportSourceSelect && entry.reportSource) {
        reportSourceSelect.value = entry.reportSource;
    } else if (reportSourceSelect) {
        reportSourceSelect.value = reportSourceSelect.options[0].value; // Default to first option
    }

    const toneSelect = document.querySelector('select[name="tone"]');
    if (toneSelect && entry.tone) {
        toneSelect.value = entry.tone;
    } else if (toneSelect) {
        toneSelect.value = toneSelect.options[0].value; // Default to first option
    }

    const queryDomainsInput = document.querySelector('input[name="query_domains"]');
    if (queryDomainsInput) {
        if (entry.queryDomains && Array.isArray(entry.queryDomains) && entry.queryDomains.length > 0) {
            queryDomainsInput.value = entry.queryDomains.join(', ');
        } else {
            queryDomainsInput.value = ''; // Clear if not present
        }
    }

    // Clear current research/report areas
    document.getElementById('output').innerHTML = '';
    document.getElementById('reportContainer').innerHTML = '';

    // Hide download bar and chat
    const stickyDownloadsBar = document.getElementById('stickyDownloadsBar');
    if (stickyDownloadsBar) {
        stickyDownloadsBar.classList.remove('visible');
    }
    const chatContainer = document.getElementById('chatContainer');
    if (chatContainer) {
        chatContainer.style.display = 'none';
    }

    // Reset UI state and report-specific buttons
    updateState('initial'); // This will hide copy buttons etc.

    // Close the history panel
    const historyPanel = document.getElementById('historyPanel');
    if (historyPanel) {
        historyPanel.classList.remove('open');
    }

    // Scroll to the form
    const formElement = document.getElementById('form');
    if (formElement) {
        formElement.scrollIntoView({ behavior: 'smooth' });
    }

    // Inform user
    showToast('研究参数已载入，你可以重新开始研究。');
  }

  // Copy entry content to clipboard
  const copyEntryToClipboard = (index) => {
    const entry = conversationHistory[index];
    if (!entry || !entry.content) return;

    const textarea = document.createElement('textarea');
    textarea.value = entry.content;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);

    // Show a toast notification
    showToast('研究内容已复制到剪贴板！');
  }

  // Show a toast notification
  const showToast = (message, duration = 3000) => {
    // Create toast element if it doesn't exist
    let toast = document.getElementById('toast-notification');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'toast-notification';
      toast.className = 'toast-notification';
      document.body.appendChild(toast);
    }

    // Set message and show
    toast.textContent = message;
    toast.classList.add('show');

    // Hide after specified duration
    setTimeout(() => {
      toast.classList.remove('show');
    }, duration);
  }

  // Save current research to history (minimal: prompt and links only)
  const saveToHistory = (report, downloadLinks) => {
    if (!downloadLinks) {
      console.error('No download links provided');
      showToast('错误：无法将研究保存到历史记录');
      return;
    }

    const prompt = document.getElementById('task').value;

    // Create links object with proper structure
    const links = {
      docx: downloadLinks.docx || '',
      md: downloadLinks.md || '',
      json: downloadLinks.json || ''
    };

    console.debug('Saving history with links:', links);

    // Create history entry with timestamp
    const historyEntry = {
      prompt,
      links,
      timestamp: new Date().toISOString()
    };

    // Add to beginning of array if it's not empty
    if (!conversationHistory) {
      conversationHistory = [];
    }

    conversationHistory.unshift(historyEntry);
    saveConversationHistory();
    renderHistoryEntries();
    document.getElementById('historyPanel').classList.add('open');

    // Prompt user about storage method
    if (cookiesEnabled) {
      showToast('研究已保存！历史记录存于浏览器 Cookie。');
    } else {
      showToast('研究已保存！历史记录存于 localStorage。');
    }
  }

  // Function to update the research icon spinning state
  const updateResearchIcon = (isSpinning) => {
    const modernSpinner = document.getElementById('modernSpinner');
    if (modernSpinner) {
      if (isSpinning) {
        modernSpinner.classList.add('spinning');
      } else {
        modernSpinner.classList.remove('spinning');
      }
    }
  };

  const startResearch = () => {
    document.getElementById('output').innerHTML = ''
    document.getElementById('reportContainer').innerHTML = ''
    dispose_socket?.() // Call previous dispose function if it exists

    // Reset report variables
    allReports = '';
    currentReport = '';
    isFirstReport = true;

    // Hide the download bar
    const stickyDownloadsBar = document.getElementById('stickyDownloadsBar');
    if (stickyDownloadsBar) {
      stickyDownloadsBar.classList.remove('visible');
    }

    // Hide the chat container
    chatContainer = document.getElementById('chatContainer');
    if (chatContainer) {
      chatContainer.style.display = 'none';
    }

    updateState('in_progress')

    addAgentResponse({
      output: '🧙‍♂️ 正在收集信息并分析你的研究主题……',
    })

    // Scroll to the "Research Progress" section
    const researchOutputContainer = document.querySelector('.research-output-container');
    if (researchOutputContainer) {
        researchOutputContainer.scrollIntoView({
            behavior: 'smooth',
            block: 'start'
        });
    }

    dispose_socket = listenToSockEvents() // Assign the new dispose function
  }

  const listenToSockEvents = () => {
    const { protocol, host, pathname } = window.location
    const ws_uri = `${protocol === 'https:' ? 'wss:' : 'ws:'
      }//${host}${pathname}ws`

    // Set a timeout for connection - if it takes too long, stop the spinner
    connectionTimeout = setTimeout(() => {
      updateResearchIcon(false);
      console.log("WebSocket connection timed out");
    }, 10000); // 10 seconds timeout

    // Configure Showdown converter to properly handle code blocks
    const converter = new showdown.Converter({
      ghCodeBlocks: true,         // GitHub style code blocks
      tables: true,               // Enable tables
      tasklists: true,            // Enable task lists
      smartIndentationFix: true,  // Fix weird indentation
      simpleLineBreaks: true,     // Treat newlines as <br>
      openLinksInNewWindow: true, // Open links in new tab
      parseImgDimensions: true    // Parse image dimensions from markdown
    });

    // Fix issues with code block formatting
    converter.setOption('literalMidWordUnderscores', true);

    // Increment connection attempts counter
    connectionAttempts++;

    // Update WebSocket status
    updateWebSocketStatus();

    socket = new WebSocket(ws_uri)
    let reportContent = ''; // Store the report content for history
    let downloadLinkData = null; // Store download links

    socket.onmessage = (event) => {
      // Reset reconnect attempts on successful message
      reconnectAttempts = 0;

      const data = JSON.parse(event.data)
      console.log("Received message:", data);  // Debug log

      // Update WebSocket metrics
      messagesReceived++;
      lastActivityTime = Date.now();
      updateWebSocketStatus();

      if (data.type === 'logs') {
        if (data.content === 'subqueries' && data.metadata && Array.isArray(data.metadata)) {
          displaySubQuestions(data.metadata)
        }
        addAgentResponse(data)
      } else if (data.type === 'report') {
        // Add to reportContent for history
        reportContent += data.output;

        // Get the current report_type
        const report_type = document.querySelector('select[name="report_type"]').value;

        // Determine if we're using detailed_report
        const isDetailedReport = report_type === 'detailed_report';

        if (isDetailedReport) {
          allReports += data.output; // Accumulate raw markdown
          // Always render the HTML of *all accumulated markdown* for detailed reports during streaming.
          // writeReport will replace the container's content.
          writeReport({ output: allReports, type: 'report' }, converter, false, false);
        } else {
          // For all other report types, append HTML of current chunk to the container.
          writeReport({ output: data.output, type: 'report' }, converter, false, true); // append = true
        }
      } else if (data.type === 'path') {
        updateState('finished')
        downloadLinkData = updateDownloadLink(data)
        isResearchActive = false;

        // Get the current report_type
        const report_type = document.querySelector('select[name="report_type"]').value;

        // Only for detailed_report, show the complete accumulated report at the end
        if (report_type === 'detailed_report' && allReports) {
          const finalData = { output: allReports, type: 'report' };
          writeReport(finalData, converter, true, false); // isFinal=true, append=false
        }

        // Save to history now that research is complete
        if (reportContent && downloadLinkData) {
          saveToHistory(reportContent, downloadLinkData);

          // Reset variables for next research session
          reportContent = '';
          allReports = '';
          currentReport = '';
          isFirstReport = true;
        }

        // Update WebSocket status
        updateWebSocketStatus();
      } else if (data.type === 'chat') {
        // Handle chat messages from the AI
        // Remove loading indicator and add AI's response
        const loadingElements = document.querySelectorAll('.chat-loading');
        if (loadingElements.length > 0) {
          loadingElements[loadingElements.length - 1].remove();
        }

        // Add AI message to chat
        if (data.content) {
          addChatMessage(data.content, false);
        }
      }
    }

    socket.onopen = (event) => {
      // Clear the connection timeout
      clearTimeout(connectionTimeout);

      // Update WebSocket metrics
      connectionStartTime = Date.now();
      lastActivityTime = Date.now();
      updateWebSocketStatus();

      // Reset reconnect attempts on successful connection
      reconnectAttempts = 0;

      // Ensure the research icon is spinning when connection is established
      updateResearchIcon(true);

      // If this is a reconnection and we're in research mode, don't send a new start command
      if (isResearchActive && lastRequestData) {
        console.log("Reconnected during active research, not sending new start command");
        return;
      }

      const task = document.getElementById('task').value
      const report_type = document.querySelector(
        'select[name="report_type"]'
      ).value
      const report_source = document.querySelector(
        'select[name="report_source"]'
      ).value
      const tone = document.querySelector('select[name="tone"]').value
      const agent = document.querySelector('input[name="agent"]:checked').value
      let source_urls = tags

      if (report_source !== 'sources' && source_urls.length > 0) {
        source_urls = source_urls.slice(0, source_urls.length - 1)
      }

      const query_domains_str = document.querySelector('input[name="query_domains"]').value
      let query_domains = []
      if (query_domains_str) {
        query_domains = query_domains_str.split(',')
          .map((domain) => domain.trim())
          .filter((domain) => domain.length > 0);
      }

      const requestData = {
        task: task,
        report_type: report_type,
        report_source: report_source,
        source_urls: source_urls,
        tone: tone,
        agent: agent,
        query_domains: query_domains,
        max_search_results: parseInt(document.getElementById('maxSearchResults').value, 10) || 5,
      }

      // Add MCP configuration if enabled
      const mcpData = collectMCPData();
      if (mcpData) {
        Object.assign(requestData, mcpData);
        console.log('Including MCP configuration:', mcpData);
      }

      // Store the request data for potential reconnection
      lastRequestData = requestData;

      socket.send(`start ${JSON.stringify(requestData)}`)
    }

    socket.onclose = (event) => {
      // Update metrics and status when connection closes
      connectionStartTime = null;
      updateWebSocketStatus();

      console.log("WebSocket connection closed", event);

      // If research is active, try to automatically reconnect
      if (isResearchActive) {
        reconnectWebSocket();
      }
    }

    socket.onerror = (error) => {
      console.error("WebSocket error:", error);
      updateWebSocketStatus();
    }

    // return dispose function
    return () => {
      try {
        isResearchActive = false; // Mark research as inactive
        if (socket && socket.readyState !== WebSocket.CLOSED && socket.readyState !== WebSocket.CLOSING) {
          socket.close();
        }

        // Update metrics on socket disposal
        connectionStartTime = null;
        updateWebSocketStatus();
      } catch (e) {
        console.error('Error closing socket:', e)
      }
    };
  }

  // Sanitize HTML before inserting it into the DOM. Report and agent content is
  // derived from untrusted sources (scraped web pages and LLM output), so it
  // must be sanitized to prevent cross-site scripting (XSS).
  const sanitizeHtml = (html) => {
    if (typeof DOMPurify !== 'undefined') {
      return DOMPurify.sanitize(html, { ADD_ATTR: ['target'] });
    }
    // Defensive fallback if DOMPurify failed to load: escape everything.
    console.warn('DOMPurify not loaded; escaping content as a fallback.');
    const tmp = document.createElement('div');
    tmp.textContent = html;
    return tmp.innerHTML;
  };

  // ============================================================
  // 后端消息中文化
  //
  // 后端通过 websocket 推送的研究进度提示，文案写在 Python 源码里
  // （gpt_researcher/skills/*.py 等），前端只是原样渲染。
  // 这里用规则表在渲染前做替换，从而不改动核心库 Python 代码。
  //
  // 实现要点：
  //  - 规则只匹配英文片段本身、不用 ^ 锚定行首，因此 emoji 前缀自动保留，
  //    也避免了在正则里书写 ZWJ 组合字符（如 🧙‍♂️）。
  //  - 顺序敏感：更具体的规则必须排在更宽泛的规则前面。
  //  - 未匹配的消息原样返回（显示英文），属于可接受的降级，不会报错。
  //  - 替换串里的 $$ 表示字面量 $，$1 表示第一个捕获组。
  // ============================================================
  const BACKEND_MESSAGE_RULES = [
    // —— 研究主流程（researcher.py）——
    [/Browsing the web to learn more about the task: ([\s\S]*?)\.\.\./, '正在浏览网页，深入了解：$1……'],
    [/Planning the research strategy and subtasks\.\.\./, '正在规划研究策略和子任务……'],
    [/Starting the research task for '([\s\S]*?)'\.\.\./, '开始研究任务：$1……'],
    [/I was unable to find relevant context in the provided sources\.\.\./, '未能从已有来源中找到相关上下文……'],
    [/Finalized research step\./, '研究步骤完成。'],
    [/Total Research Costs: \$([\d.]+)/, '累计研究成本：$$$1'],
    [/I will conduct my research based on the following queries: ([\s\S]*?)\.\.\./, '我将基于以下查询展开研究：$1……'],
    [/Researching for relevant information across multiple sources\.\.\./, '正在从多个来源检索相关信息……'],
    [/Added source url to research: ([\s\S]*?)\s*$/, '已添加来源链接：$1'],
    [/Research Progress: ([\d.]+)%/, '研究进度：$1%'],
    [/Running deep MCP research for: ([\s\S]*?)$/, '正在对以下内容做深度 MCP 研究：$1'],
    [/Running research for '([\s\S]*?)'\.\.\./, '正在研究：$1……'],
    [/No content found for '([\s\S]*?)'\.\.\./, '未找到与「$1」相关的内容……'],
    [/Error processing '([\s\S]*?)': ([\s\S]*)$/, '处理「$1」时出错：$2'],
    [/Combined research context: ([\s\S]*)$/, '合并后的研究上下文：$1'],
    [/with web content/, '含网页内容'],
    [/0 MCP sources, no web content/, '0 个 MCP 来源，无网页内容'],

    // —— MCP 相关（researcher.py）——
    [/MCP research disabled by configuration/, '按配置已禁用 MCP 研究'],
    [/MCP Fast: Running once for main query \(performance mode\)/, 'MCP 快速模式：仅对主查询运行一次（性能优先）'],
    [/MCP Deep: Will run for each sub-query \(thorough mode\)/, 'MCP 深度模式：将对每个子查询运行（更全面）'],
    [/Cached ([\s\S]*?) MCP results from query ([\s\S]*?)$/, '已缓存 $2 的 $1 条 MCP 结果'],
    [/Skipping Tavily MCP \(redundant with direct Tavily retriever\) to avoid double API cost/, '跳过 Tavily MCP（与直连 Tavily 检索重复），以避免重复计费'],
    [/Reusing cached MCP results \(([\s\S]*?) sources\) for: ([\s\S]*?)$/, '对「$2」复用已缓存的 MCP 结果（$1 个来源）'],
    [/MCP cache unavailable, running MCP research for: ([\s\S]*?)$/, 'MCP 缓存不可用，正在对以下内容执行 MCP 研究：$1'],
    [/Stage 1: Selecting optimal MCP tools for: ([\s\S]*?)$/, '阶段 1：为以下内容挑选最优 MCP 工具：$1'],
    [/MCP research completed: ([\s\S]*?) intelligent results obtained/, 'MCP 研究完成：获得 $1 条有效结果'],
    [/Consulting MCP server\(s\) for information on: ([\s\S]*?)$/, '正在向 MCP 服务器查询：$1'],
    [/Retrieved ([\s\S]*?) results from MCP server/, '已从 MCP 服务器获取 $1 条结果'],
    [/No relevant information found via MCP for: ([\s\S]*?)$/, 'MCP 未找到与以下内容相关的信息：$1'],
    [/No relevant information found from MCP server for: ([\s\S]*?)$/, 'MCP 服务器未找到与以下内容相关的信息：$1'],
    [/MCP research error for query ([\s\S]*?), continuing with other sources/, '查询 $1 的 MCP 研究出错，将继续使用其他来源'],
    [/MCP research error: ([\s\S]*?) - continuing with other sources/, 'MCP 研究出错：$1——将继续使用其他来源'],
    [/Error retrieving information from MCP server: ([\s\S]*)$/, '从 MCP 服务器获取信息出错：$1'],

    // —— 报告写作（writer.py）——
    [/Writing report for '([\s\S]*?)'\.\.\./, '正在撰写报告：$1……'],
    [/Report written for '([\s\S]*?)'$/, '报告已完成：$1'],
    [/Writing conclusion for '([\s\S]*?)'\.\.\./, '正在撰写结论：$1……'],
    [/Conclusion written for '([\s\S]*?)'$/, '结论已完成：$1'],
    [/Writing introduction for '([\s\S]*?)'\.\.\./, '正在撰写引言：$1……'],
    [/Introduction written for '([\s\S]*?)'$/, '引言已完成：$1'],
    [/Generating subtopics for '([\s\S]*?)'\.\.\./, '正在生成子主题：$1……'],
    [/Subtopics generated for '([\s\S]*?)'$/, '子主题已生成：$1'],
    [/Generating draft section titles for '([\s\S]*?)'\.\.\./, '正在生成章节标题草稿：$1……'],
    [/Draft section titles generated for '([\s\S]*?)'$/, '章节标题草稿已生成：$1'],
    [/pre-generated images available for embedding/, '张预生成图片可用于嵌入'],

    // —— 网页抓取（browser.py）——
    [/Scraping content from ([\s\S]*?) URLs\.\.\./, '正在抓取 $1 个网页的内容……'],
    [/Scraped ([\s\S]*?) pages of content/, '已抓取 $1 个页面的内容'],
    [/Selected ([\s\S]*?) new images from ([\s\S]*?) total images/, '从 $2 张图片中选出 $1 张新图片'],
    [/Scraping complete/, '抓取完成'],

    // —— 上下文处理（context_manager.py）——
    [/Getting relevant content based on query: ([\s\S]*?)\.\.\./, '正在根据查询获取相关内容：$1……'],
    [/Getting relevant written content based on query: ([\s\S]*?)\.\.\./, '正在根据查询获取已撰写内容：$1……'],

    // —— 来源可信度评估（curator.py）——
    [/Evaluating and curating sources by credibility and relevance\.\.\./, '正在按可信度和相关性评估、筛选来源……'],
    [/Verified and ranked top ([\s\S]*?) most reliable sources/, '已验证并排序出最可靠的前 $1 个来源'],
    [/Source verification failed: ([\s\S]*)$/, '来源验证失败：$1'],

    // —— 配图生成（image_generator.py）——
    [/Analyzing research context for visualization opportunities\.\.\./, '正在分析研究上下文，寻找可视化机会……'],
    [/Analyzing report for image generation opportunities\.\.\./, '正在分析报告，寻找配图机会……'],
    [/Identified ([\s\S]*?) visualization concepts, generating images\.\.\./, '已识别 $1 个可视化方案，正在生成图片……'],
    [/Found ([\s\S]*?) image placeholders to process/, '发现 $1 个待处理的图片占位符'],
    [/Found ([\s\S]*?) sections that would benefit from images/, '发现 $1 个适合配图的章节'],
    [/Generating image ([\s\S]*?): ([\s\S]*?)\.\.\./, '正在生成图片 $1：$2……'],
    [/Image generated for: ([\s\S]*?)$/, '图片已生成：$1'],
    [/Generated: ([\s\S]*?)\.\.\./, '已生成：$1……'],
    [/Failed to generate image: ([\s\S]*)$/, '图片生成失败：$1'],
    [/Failed to generate: ([\s\S]*)$/, '生成失败：$1'],
    [/images ready for report embedding/, '张图片已就绪，可用于报告嵌入'],
    [/No images could be generated/, '未能生成任何图片'],
    [/Successfully generated and embedded ([\s\S]*?) images/, '已成功生成并嵌入 $1 张图片'],
    [/Successfully generated ([\s\S]*?) inline images/, '已成功生成 $1 张内嵌图片'],
    [/No sections identified that would benefit from images/, '未发现适合配图的章节'],

    // —— 后端服务端消息（backend/server/*.py）——
    [/Task already running\. Please wait\./, '已有任务正在运行，请稍候。'],
    [/Unknown command received by server/, '服务器收到未知指令'],
    [/No message provided\./, '未提供消息内容。'],
    [/Chat functionality is not available\. Please check the server configuration\./, '对话功能不可用，请检查服务器配置。'],
    [/Invalid message format - ([\s\S]*)$/, '消息格式无效：$1'],
    [/Error processing your message: ([\s\S]*)$/, '处理你的消息时出错：$1'],
    [/MCP enabled with strategy '([\s\S]*?)' and ([\s\S]*?) server\(s\)/, 'MCP 已启用，策略为「$1」，共 $2 个服务器'],
  ];

  // 把后端推来的英文消息转成中文；未命中的部分保持原样。
  //
  // 注意：这里必须把所有命中的规则都应用一遍，不能命中第一条就返回。
  // 有些消息是多行的（例如 "Finalized research step.\n💸 Total Research
  // Costs: $0.12"），每条子句需要各自匹配各自的规则。
  // 已翻译的文本是中文，不会再命中英文规则，因此反复应用是安全的。
  const translateBackendMessage = (text) => {
    if (typeof text !== 'string' || !text) return text;
    let result = text;
    for (let i = 0; i < BACKEND_MESSAGE_RULES.length; i++) {
      const pattern = BACKEND_MESSAGE_RULES[i][0];
      if (pattern.test(result)) {
        result = result.replace(pattern, BACKEND_MESSAGE_RULES[i][1]);
      }
    }
    return result;
  };

  const addAgentResponse = (data) => {
    const output = document.getElementById('output');
    const responseDiv = document.createElement('div');
    responseDiv.className = 'agent_response';
    responseDiv.innerHTML = sanitizeHtml(translateBackendMessage(data.output));
    output.appendChild(responseDiv);
    output.scrollTop = output.scrollHeight;
    output.style.display = 'block';
  }

  const displaySubQuestions = (questions) => {
    const output = document.getElementById('output');
    const container = document.createElement('div');
    container.className = 'sub-questions';

    const heading = document.createElement('p');
    heading.className = 'sub-questions-heading';
    heading.textContent = '🤔 正在从多个角度思考你的问题';
    container.appendChild(heading);

    const list = document.createElement('div');
    list.className = 'sub-questions-list';
    questions.forEach((q) => {
      const pill = document.createElement('span');
      pill.className = 'sub-question-pill';
      pill.textContent = q;
      list.appendChild(pill);
    });
    container.appendChild(list);

    output.appendChild(container);
    output.scrollTop = output.scrollHeight;
    output.style.display = 'block';
  }

  const writeReport = (data, converter, isFinal = false, append = false) => {
    const reportContainer = document.getElementById('reportContainer');

    // Convert markdown to HTML, then sanitize to prevent XSS from untrusted
    // report content (scraped pages / LLM output).
    const markdownOutput = sanitizeHtml(converter.makeHtml(data.output));

    // If this is the final report or we should append
    if (isFinal) {
      // For final reports, always replace content
      reportContainer.innerHTML = markdownOutput;
    } else if (append) {
      // Append mode - add to existing content
      reportContainer.innerHTML += markdownOutput;
    } else {
      // Replace mode - overwrite existing content
      reportContainer.innerHTML = markdownOutput;
    }

    // Auto-scroll to the bottom of the container
    reportContainer.scrollTop = reportContainer.scrollHeight;
  }

  const updateDownloadLink = (data) => {
    if (!data.output) {
      console.error('No output data received');
      return;
    }

    const { docx, md, json } = data.output;
    console.log('Received paths:', { docx, md, json });

    // Store these links for history
    const currentLinks = { docx, md, json };

    // Helper function to safely update link
    const updateLink = (id, path) => {
      const element = document.getElementById(id);
      if (element && path) {
        console.log(`Setting ${id} href to:`, path);
        element.setAttribute('href', path);
        element.classList.remove('disabled');
      } else {
        console.warn(`Either element ${id} not found or path not provided`);
      }
    };

    // Update links in sticky download bar
    updateLink('downloadLinkWord', docx);
    updateLink('downloadLinkMd', md);
    updateLink('downloadLinkJson', json);

    // Update duplicate buttons above the report
    updateLink('downloadLinkWordTop', docx);
    updateLink('downloadLinkMdTop', md);
    updateLink('downloadLinkJsonTop', json);

    // Make sure download buttons are visible when download links are ready
    showDownloadPanels();

    // Return links for history saving
    return currentLinks;
  }

  const copyToClipboard = () => {
    const textarea = document.createElement('textarea')
    textarea.id = 'temp_element'
    textarea.style.height = 0
    document.body.appendChild(textarea)
    textarea.value = document.getElementById('reportContainer').innerText
    const selector = document.querySelector('#temp_element')
    selector.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)

    // Show a temporary success message with icon change and toast notification
    const copyBtn = document.getElementById('copyToClipboard');
    const copyBtnTop = document.getElementById('copyToClipboardTop');

    // Function to reset the icon for both buttons
    const resetIcons = () => {
      if (copyBtn) {
        copyBtn.innerHTML = '<i class="fas fa-copy"></i> 复制';
      }
      if (copyBtnTop) {
        copyBtnTop.innerHTML = '<i class="fas fa-copy"></i>';
      }
    };

    // Change to green check mark
    if (copyBtn) {
      copyBtn.innerHTML = '<i class="fas fa-check" style="color: green;"></i> 已复制！';
    }
    if (copyBtnTop) {
      copyBtnTop.innerHTML = '<i class="fas fa-check" style="color: green;"></i>';
    }

    // Show toast notification
    showToast('已复制到剪贴板！');

    // Reset the button after 3 seconds
    setTimeout(resetIcons, 3000);
  }

  const updateState = (state) => {
    var status = ''
    switch (state) {
      case 'in_progress':
        status = '研究进行中……'
        setReportActionsStatus('disabled')
        isResearchActive = true;
        // Make the research icon spin
        updateResearchIcon(true);
        // Hide chat container during research
        chatContainer = document.getElementById('chatContainer');
        if (chatContainer) {
          chatContainer.style.display = 'none';
        }
        // Hide the copy button in the header
        const copyBtnTop = document.getElementById('copyToClipboardTop');
        if (copyBtnTop) {
          copyBtnTop.style.display = 'none';
        }
        // Hide the JSON button container
        const jsonContainer = document.getElementById('jsonButtonContainer');
        if (jsonContainer) {
          jsonContainer.style.display = 'none';
        }
        break
      case 'finished':
        status = '研究完成！'
        setReportActionsStatus('enabled')
        isResearchActive = false;
        // Stop the research icon spinning
        updateResearchIcon(false);

        // Show download panels and hide feature panels when research is finished
        showDownloadPanels();

        // Enable the copy button
        const copyButton = document.getElementById('copyToClipboard');
        if (copyButton) {
          copyButton.classList.remove('disabled');
        }

        // Show copy button in the header
        const topCopyButton = document.getElementById('copyToClipboardTop');
        if (topCopyButton) {
          topCopyButton.style.display = 'inline-block';
          topCopyButton.addEventListener('click', copyToClipboard);
        }

        // Show JSON button container
        const jsonButtonContainer = document.getElementById('jsonButtonContainer');
        if (jsonButtonContainer) {
          jsonButtonContainer.style.display = 'block';
        }

        // Show chat container when research is finished
        chatContainer = document.getElementById('chatContainer');
        if (chatContainer) {
          chatContainer.style.display = 'block';
          // Initialize chat if not already initialized
          initChat();
        }
        break
      case 'error':
        status = '研究失败！'
        setReportActionsStatus('disabled')
        isResearchActive = false;
        // Stop the research icon spinning
        updateResearchIcon(false);
        break
      case 'initial':
        status = ''
        setReportActionsStatus('hidden')
        isResearchActive = false;
        // Make sure the research icon is not spinning initially
        updateResearchIcon(false);
        // Hide the copy button in the header
        const initialCopyBtnTop = document.getElementById('copyToClipboardTop');
        if (initialCopyBtnTop) {
          initialCopyBtnTop.style.display = 'none';
        }
        // Hide the JSON button container
        const initialJsonContainer = document.getElementById('jsonButtonContainer');
        if (initialJsonContainer) {
          initialJsonContainer.style.display = 'none';
        }
        break
      default:
        setReportActionsStatus('disabled')
    }
    document.getElementById('status').innerHTML = status
    if (document.getElementById('status').innerHTML == '') {
      document.getElementById('status').style.display = 'none'
    } else {
      document.getElementById('status').style.display = 'block'
    }
  }

  /**
   * Shows or hides the download and copy buttons
   * @param {str} status Kind of hacky. Takes "enabled", "disabled", or "hidden". "Hidden is same as disabled but also hides the div"
   */
  const setReportActionsStatus = (status) => {
    const reportActions = document.getElementById('reportActions')
    // Disable everything in reportActions until research is finished

    if (status == 'enabled') {
      reportActions.querySelectorAll('a').forEach((link) => {
        link.classList.remove('disabled')
        link.removeAttribute('onclick')
        reportActions.style.display = 'block'
      })
    } else {
      reportActions.querySelectorAll('a').forEach((link) => {
        link.classList.add('disabled')
        link.setAttribute('onclick', 'return false;')
      })
      if (status == 'hidden') {
        reportActions.style.display = 'none'
      }
    }
  }

  // 来源 URL 标签输入功能已随旧界面移除（#tags-input / #custom_source 都不存在）。
  // tags 数组本身要保留为空数组：请求负载仍会读取它（scripts.js:969 的 source_urls）。
  const tags = [];

  // Function to show download bar and enable buttons
  const showDownloadPanels = () => {
    // Show the bar by adding the visible class
    const stickyDownloadsBar = document.getElementById('stickyDownloadsBar');
    if (stickyDownloadsBar) {
      stickyDownloadsBar.classList.add('visible');
    }

    // Enable all download buttons
    const downloadButtons = document.querySelectorAll('.download-option-btn, .report-action-btn');
    downloadButtons.forEach(button => {
      button.classList.remove('disabled');
    });

    // Make top buttons report-actions section visible
    const reportActions = document.querySelector('.report-actions');
    if (reportActions) {
      reportActions.style.display = 'flex';
    }
  }

  // --- Storage Helpers (Cookies or LocalStorage) ---
  function setCookie(name, value, days) {
    // Maximum cookie size is around 4KB (4096 bytes)
    const MAX_COOKIE_SIZE = 4000;

    // If cookies are disabled, use localStorage instead
    if (!cookiesEnabled) {
      try {
        localStorage.setItem(name, value);
        console.debug(`Data saved to localStorage: ${name}`);
        return true;
      } catch (e) {
        console.error("Error saving to localStorage:", e);
        return false;
      }
    }

    let expires = '';
    if (days) {
      const date = new Date();
      date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
      expires = '; expires=' + date.toUTCString();
    }

    // Encode the value
    const encodedValue = encodeURIComponent(value);

    // Calculate cookie size
    const cookieSize = (name + '=' + encodedValue + expires + '; path=/').length;
    console.debug(`Setting cookie: ${name}, size: ${cookieSize} bytes`);

    // If cookie is too large, display warning and truncate history
    if (cookieSize > MAX_COOKIE_SIZE) {
      console.warn(`Cookie size (${cookieSize} bytes) exceeds the ${MAX_COOKIE_SIZE} bytes limit!`);
      showToast('警告：历史记录超出 Cookie 容量上限！最早的条目将被移除。');

      if (name === 'conversationHistory') {
        try {
          // Parse, reduce entries, and try again
          const historyData = JSON.parse(value);
          if (Array.isArray(historyData) && historyData.length > 1) {
            // Remove the last entry and try again recursively
            const reducedHistory = historyData.slice(0, -1);
            console.debug(`Reducing history from ${historyData.length} to ${reducedHistory.length} entries`);
            setCookie(name, JSON.stringify(reducedHistory), days);
            return; // Exit after recursive call
          }
        } catch (e) {
          console.error('Could not parse history to reduce size:', e);
        }
      }

      return false; // Indicate failure
    }

    // Set the cookie
    document.cookie = name + '=' + encodedValue + expires + '; path=/';
    console.debug(`Cookie set: ${name}`);
    return true; // Indicate success
  }

  function getCookie(name) {
    console.debug(`Getting data: ${name}`);

    // If cookies are disabled, use localStorage instead
    if (!cookiesEnabled) {
      try {
        const value = localStorage.getItem(name);
        if (value) {
          console.debug(`Data found in localStorage: ${name}, length: ${value.length} chars`);
          return value;
        }
        console.debug(`Data not found in localStorage: ${name}`);
        return null;
      } catch (e) {
        console.error("Error retrieving from localStorage:", e);
        return null;
      }
    }

    const nameEQ = name + '=';
    const ca = document.cookie.split(';');
    for (let i = 0; i < ca.length; i++) {
      let c = ca[i];
      while (c.charAt(0) == ' ') c = c.substring(1, c.length);
      if (c.indexOf(nameEQ) == 0) {
        const value = decodeURIComponent(c.substring(nameEQ.length, c.length));
        console.debug(`Found cookie: ${name}, length: ${value.length} chars`);
        return value;
      }
    }
    console.debug(`Cookie not found: ${name}`);
    return null;
  }

  function deleteCookie(name) {
    console.debug(`Deleting storage: ${name}`);

    // If cookies are disabled, use localStorage instead
    if (!cookiesEnabled) {
      try {
        localStorage.removeItem(name);
        return;
      } catch (e) {
        console.error("Error removing from localStorage:", e);
        return;
      }
    }

    document.cookie = name + '=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
  }
  // --- End Storage Helpers ---

  // Debug Helper - check cookie status
  const checkCookieStatus = () => {
    if (!cookiesEnabled) {
      const storageData = localStorage.getItem('conversationHistory');
      if (storageData) {
        const byteSize = new Blob([storageData]).size;
        const kilobyteSize = (byteSize / 1024).toFixed(2);

        try {
          const parsed = JSON.parse(storageData);
          const entryCount = Array.isArray(parsed) ? parsed.length : 0;

          showToast(`使用 localStorage：${kilobyteSize}KB，${entryCount} 条记录`);
          console.debug(`LocalStorage size: ${byteSize} bytes, ${kilobyteSize}KB`);
          console.debug(`LocalStorage entries: ${entryCount}`);
        } catch (e) {
          showToast(`localStorage 中存在无效数据：${kilobyteSize}KB`);
          console.error('LocalStorage parse error:', e);
        }
      } else {
        showToast('localStorage 中未找到研究历史');
      }
      return;
    }

    const allCookies = document.cookie;
    console.debug('All cookies:', allCookies);

    const conversationCookie = getCookie('conversationHistory');
    if (conversationCookie) {
      const byteSize = new Blob([conversationCookie]).size;
      const kilobyteSize = (byteSize / 1024).toFixed(2);

      try {
        const parsed = JSON.parse(conversationCookie);
        const entryCount = Array.isArray(parsed) ? parsed.length : 0;

        showToast(`找到 Cookie：${kilobyteSize}KB，${entryCount} 条研究记录`);
        console.debug(`Cookie size: ${byteSize} bytes, ${kilobyteSize}KB`);
        console.debug(`Cookie entries: ${entryCount}`);
      } catch (e) {
        showToast(`找到 Cookie 但内容无效：${kilobyteSize}KB`);
        console.error('Cookie parse error:', e);
      }
    } else {
      showToast('未找到研究历史 Cookie');
    }
  }

  // Export history to a downloadable JSON file
  const exportHistory = () => {
    try {
      if (!conversationHistory || conversationHistory.length === 0) {
        showToast('没有可导出的研究历史');
        return;
      }

      // Create a formatted JSON string with pretty-printing
      const historyJson = JSON.stringify(conversationHistory, null, 2);

      // Create a Blob containing the data
      const blob = new Blob([historyJson], { type: 'application/json' });

      // Create an object URL for the blob
      const url = URL.createObjectURL(blob);

      // Create a temporary link element
      const link = document.createElement('a');
      link.href = url;

      // Set download attribute with filename
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      link.download = `research-history-${timestamp}.json`;

      // Append to the document
      document.body.appendChild(link);

      // Programmatically click the link to trigger the download
      link.click();

      // Clean up
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      showToast('研究历史已导出为 JSON 文件');
      console.debug('History exported, entries:', conversationHistory.length);
    } catch (error) {
      console.error('Error exporting history:', error);
      showToast('导出研究历史失败');
    }
  }

  // Trigger the file input for importing history
  const triggerImportHistory = () => {
    const fileInput = document.getElementById('historyFileInput');
    if (fileInput) {
      fileInput.click();
    } else {
      showToast('导入功能不可用');
    }
  }

  // Handle the file import for history
  const handleFileImport = (event) => {
    const file = event.target.files[0];
    if (!file) {
      return;
    }

    const reader = new FileReader();

    reader.onload = (e) => {
      try {
        const content = e.target.result;
        const importedData = JSON.parse(content);

        // Validate the imported data
        if (!Array.isArray(importedData)) {
          throw new Error('Imported data is not an array');
        }

        // Check if each entry has the required fields
        const validEntries = importedData.filter(entry => {
          return entry &&
            typeof entry === 'object' &&
            (entry.prompt || entry.task) && // Allow both prompt and legacy task field
            (entry.links || entry.downloadLinks); // Allow both links and legacy downloadLinks
        });

        if (validEntries.length === 0) {
          showToast('导入的文件中未找到有效的研究记录');
          return;
        }

        // Map the entries to the current structure if needed
        const mappedEntries = validEntries.map(entry => {
          return {
            prompt: entry.prompt || entry.task || '',
            links: entry.links || entry.downloadLinks || {},
            timestamp: entry.timestamp || new Date().toISOString()
          };
        });

        // Confirm before overwriting existing history
        if (conversationHistory && conversationHistory.length > 0) {
          if (confirm(`你已有 ${conversationHistory.length} 条研究记录。请选择：
- 点击"确定"：把导入的历史与现有历史合并
- 点击"取消"：用导入的数据替换全部现有历史`)) {
            // Merge with existing history
            conversationHistory = [...mappedEntries, ...conversationHistory];
          } else {
            // Replace existing history
            conversationHistory = mappedEntries;
          }
        } else {
          // No existing history, just set the imported data
          conversationHistory = mappedEntries;
        }

        // Save the new history and update the UI
        saveConversationHistory();
        renderHistoryEntries();

        showToast(`成功导入 ${validEntries.length} 条研究记录`);
        console.debug('Research history imported, valid entries:', validEntries.length);

      } catch (error) {
        console.error('Error importing history:', error);
        showToast('导入研究历史失败：文件格式无效');
      }

      // Reset the file input so the same file can be selected again
      event.target.value = '';
    };

    reader.onerror = () => {
      console.error('Error reading file');
      showToast('读取导入文件失败');
      event.target.value = '';
    };

    reader.readAsText(file);
  }

  // Initialize chat functionality
  const initChat = () => {
    const chatInput = document.getElementById('chatInput');
    const sendChatBtn = document.getElementById('sendChatBtn');
    const voiceInputBtn = document.getElementById('voiceInputBtn');

    if (!chatInput || !sendChatBtn) return;

    // Clear previous messages
    const chatMessages = document.getElementById('chatMessages');
    if (chatMessages) {
      chatMessages.innerHTML = '';
    }

    // Add event listeners for chat input
    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
      }
    });

    sendChatBtn.addEventListener('click', sendChatMessage);

    // Initialize speech recognition if supported
    if (voiceInputBtn) {
      initSpeechRecognition(voiceInputBtn, chatInput);
    }

    // Auto-resize textarea as content grows
    chatInput.addEventListener('input', () => {
      chatInput.style.height = 'auto';
      chatInput.style.height = (chatInput.scrollHeight) + 'px';
    });

    // Add welcome message
    addChatMessage('我可以回答关于这份研究报告的问题。你想了解什么？', false);
  }

  // Initialize speech recognition
  const initSpeechRecognition = (button, inputElement) => {
    // Check if browser supports speech recognition
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
      console.warn('Speech recognition not supported in this browser');
      button.style.display = 'none';
      return;
    }

    const recognition = new SpeechRecognition();

    // Configure speech recognition
    recognition.continuous = false;
    recognition.lang = 'zh-CN';
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    let isListening = false;
    let finalTranscript = '';

    // Add event listeners for speech recognition
    recognition.onstart = () => {
      isListening = true;
      finalTranscript = '';
      button.classList.add('listening');
      button.innerHTML = '<i class="fas fa-microphone-slash"></i>';
      button.title = '停止聆听';

      // Show visual feedback
      showToast('正在聆听……', 1000);
    };

    recognition.onresult = (event) => {
      let interimTranscript = '';

      // Loop through the results
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;

        if (event.results[i].isFinal) {
          finalTranscript += transcript;
        } else {
          interimTranscript += transcript;
        }
      }

      // Update the input element with the transcription
      inputElement.value = finalTranscript + interimTranscript;

      // Trigger input event to resize textarea
      const inputEvent = new Event('input', { bubbles: true });
      inputElement.dispatchEvent(inputEvent);
    };

    recognition.onerror = (event) => {
      console.error('Speech recognition error', event.error);
      resetRecognition();

      if (event.error === 'not-allowed') {
        showToast('麦克风权限被拒绝，请在浏览器设置中允许访问麦克风。', 3000);
      } else {
        showToast('语音识别错误：' + event.error, 3000);
      }
    };

    recognition.onend = () => {
      resetRecognition();
    };

    // Reset the recognition state
    const resetRecognition = () => {
      isListening = false;
      button.classList.remove('listening');
      button.innerHTML = '<i class="fas fa-microphone"></i>';
      button.title = '使用语音输入';
    };

    // Toggle speech recognition on button click
    button.addEventListener('click', () => {
      if (isListening) {
        recognition.stop();
      } else {
        recognition.start();
      }
    });
  };

  // Create a new function to handle WebSocket reconnection
  const reconnectWebSocket = (message = null) => {
    // Don't attempt too many reconnections
    if (reconnectAttempts >= maxReconnectAttempts) {
      console.error(`Failed to reconnect after ${maxReconnectAttempts} attempts`);
      addChatMessage(`重连 ${maxReconnectAttempts} 次仍失败，请刷新页面。`, false);
      return false;
    }

    reconnectAttempts++;

    // Calculate backoff time (exponential backoff)
    const backoff = reconnectInterval * Math.pow(1.5, reconnectAttempts - 1);
    console.log(`Attempting to reconnect (${reconnectAttempts}/${maxReconnectAttempts}) in ${backoff}ms...`);

    // Show reconnection status to user
    addChatMessage(`连接已断开，正在尝试重连（${reconnectAttempts}/${maxReconnectAttempts}）……`, false);

    // Try to reconnect after delay
    setTimeout(() => {
      try {
        // Setup new WebSocket connection
        dispose_socket = listenToSockEvents();

        // Set up a one-time handler to send the message after reconnection
        if (message) {
          const messageToSend = message;
          const checkConnectionAndSend = () => {
            if (socket && socket.readyState === WebSocket.OPEN) {
              console.log("Reconnected successfully, sending queued message");
              socket.send(messageToSend);
              return true;
            } else if (reconnectAttempts < maxReconnectAttempts) {
              console.log("Socket not ready yet, retrying...");
              setTimeout(checkConnectionAndSend, 1000);
              return false;
            }
            return false;
          };

          setTimeout(checkConnectionAndSend, 1000);
        }

        return true;
      } catch (e) {
        console.error("Error during reconnection:", e);
        return false;
      }
    }, backoff);

    return true;
  };

  // Send a chat message
  const sendChatMessage = () => {
    const chatInput = document.getElementById('chatInput');
    if (!chatInput || !chatInput.value.trim()) return;

    const message = chatInput.value.trim();

    // Add user message to chat
    addChatMessage(message, true);

    // Clear input
    chatInput.value = '';
    chatInput.style.height = 'auto';

    // Add loading indicator
    const loadingId = addLoadingIndicator();

    // Prepare the message to send
    const messageToSend = `chat ${JSON.stringify({ message: message })}`;

    // Send message through WebSocket
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(messageToSend);
    } else {
      // If socket is closed, try to reconnect
      removeLoadingIndicator(loadingId);

      // Reset reconnect attempts if this is a new chat session
      if (reconnectAttempts >= maxReconnectAttempts) {
        reconnectAttempts = 0;
      }

      // Attempt to reconnect and queue the message to be sent after reconnection
      if (!reconnectWebSocket(messageToSend)) {
        // If reconnection fails or max attempts reached
        addChatMessage('无法发送消息，连接不可用。', false);
      }
    }
  }

  // Add a chat message to the UI
  const addChatMessage = (message, isUser = false) => {
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return;

    const messageEl = document.createElement('div');
    messageEl.className = `chat-message ${isUser ? 'user-message' : 'ai-message'}`;

    // Process message for AI responses (convert markdown to HTML for AI messages)
    let processedMessage = message;
    if (!isUser) {
      // The server sends some chat replies in English (see backend/server/
      // server_utils.py); translate before markdown conversion so the rules
      // match the original plain text rather than generated HTML.
      message = translateBackendMessage(message);
      processedMessage = message;
      // Use showdown for markdown conversion
      const converter = new showdown.Converter({
        ghCodeBlocks: true,
        tables: true,
        tasklists: true,
        openLinksInNewWindow: true
      });
      processedMessage = converter.makeHtml(message);
    }

    // Set message content
    messageEl.innerHTML = isUser ? escapeHtml(processedMessage) : processedMessage;

    // Add timestamp
    const timestampEl = document.createElement('div');
    timestampEl.className = 'chat-timestamp';
    const now = new Date();
    timestampEl.textContent = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    messageEl.appendChild(timestampEl);

    // Add to chat container
    chatMessages.appendChild(messageEl);

    // Scroll to bottom
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // Add a loading indicator
  const addLoadingIndicator = () => {
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return null;

    const loadingId = 'loading-' + Date.now();
    const loadingEl = document.createElement('div');
    loadingEl.className = 'chat-message ai-message chat-loading';
    loadingEl.id = loadingId;

    // Create the dots
    for (let i = 0; i < 3; i++) {
      const dot = document.createElement('div');
      dot.className = 'chat-dot';
      loadingEl.appendChild(dot);
    }

    chatMessages.appendChild(loadingEl);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    return loadingId;
  }

  // Remove loading indicator
  const removeLoadingIndicator = (loadingId) => {
    if (!loadingId) return;

    const loadingEl = document.getElementById(loadingId);
    if (loadingEl) {
      loadingEl.remove();
    }
  }

  // Escape HTML to prevent XSS in user messages
  const escapeHtml = (text) => {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Initialize expand buttons
  const initExpandButtons = () => {
    // Report container expand button
    const expandReportBtn = document.getElementById('expandReportBtn');
    if (expandReportBtn) {
      expandReportBtn.addEventListener('click', () => {
        const reportContainer = document.querySelector('.report-container');
        toggleExpand(reportContainer);
      });
    }

    // Chat container expand button
    const expandChatBtn = document.getElementById('expandChatBtn');
    if (expandChatBtn) {
      expandChatBtn.addEventListener('click', () => {
        const chatContainer = document.getElementById('chatContainer');
        toggleExpand(chatContainer);
      });
    }

    // Output container expand button
    const expandOutputBtn = document.getElementById('expandOutputBtn');
    if (expandOutputBtn) {
      expandOutputBtn.addEventListener('click', () => {
        const outputContainer = document.querySelector('.research-output-container');
        toggleExpand(outputContainer);
      });
    }

    // Close expanded view when ESC key is pressed
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const expandedElements = document.querySelectorAll('.expanded-view');
        expandedElements.forEach(el => {
          // Reset the button icon
          const button = el.querySelector('.expand-button i');
          if (button) {
            button.classList.remove('fa-compress-alt');
            button.classList.add('fa-expand-alt');
          }

          // Reset content container styles
          const contentContainers = el.querySelectorAll('#reportContainer, #output, #chatMessages');
          contentContainers.forEach(container => {
            if (container) {
              container.style.maxHeight = '';
            }
          });

          // Remove expanded-view class
          el.classList.remove('expanded-view');
        });
      }
    });
  }

  // Toggle expand mode for an element
  const toggleExpand = (element) => {
    if (!element) return;

    // Toggle expanded-view class
    element.classList.toggle('expanded-view');

    // Change button icon and title based on state
    const buttonIcon = element.querySelector('.expand-button i');
    const button = element.querySelector('.expand-button');

    if (buttonIcon && button) {
      if (element.classList.contains('expanded-view')) {
        buttonIcon.classList.remove('fa-compress-alt');
        buttonIcon.classList.add('fa-compress-alt');
        button.title = '收起'; // Update title to Collapse

        // Find content containers and expand their height
        const contentContainers = element.querySelectorAll('#reportContainer, #output, #chatMessages');
        contentContainers.forEach(container => {
          if (container) {
            // Set expanded heights - no positioning changes
            if (container.id === 'reportContainer') {
              container.style.maxHeight = '800px'; // Fixed expanded height for report
            } else {
              container.style.maxHeight = '600px'; // Fixed expanded height for other content
            }
          }
        });
      } else {
        buttonIcon.classList.remove('fa-compress-alt');
        buttonIcon.classList.add('fa-expand-alt');
        button.title = '展开'; // Update title to Expand

        // Reset heights back to original when collapsed
        const contentContainers = element.querySelectorAll('#reportContainer, #output, #chatMessages');
        contentContainers.forEach(container => {
          if (container) {
            container.style.maxHeight = '';
          }
        });
      }
    }
  }

  // MCP Configuration Management
  
  // Initialize MCP functionality
  const initMCPSection = () => {
    const mcpEnabled = document.getElementById('mcpEnabled');
    const mcpConfigSection = document.getElementById('mcpConfigSection');
    const mcpInfoBtn = document.getElementById('mcpInfoBtn');
    const mcpConfig = document.getElementById('mcpConfig');
    const mcpFormatBtn = document.getElementById('mcpFormatBtn');
    const mcpExampleLink = document.getElementById('mcpExampleLink');

    if (!mcpEnabled || !mcpConfigSection) {
      console.warn('MCP elements not found');
      return;
    }

    // Toggle MCP config section
    mcpEnabled.addEventListener('change', () => {
      if (mcpEnabled.checked) {
        mcpConfigSection.style.display = 'block';
        updateRetrieverForMCP(true);
      } else {
        mcpConfigSection.style.display = 'none';
        updateRetrieverForMCP(false);
      }
    });

    // MCP info modal
    if (mcpInfoBtn) {
      mcpInfoBtn.addEventListener('click', showMCPInfo);
    }

    // JSON validation and formatting
    if (mcpConfig) {
      mcpConfig.addEventListener('input', validateMCPConfig);
      mcpConfig.addEventListener('blur', validateMCPConfig);
    }

    if (mcpFormatBtn) {
      mcpFormatBtn.addEventListener('click', formatMCPConfig);
    }

    if (mcpExampleLink) {
      mcpExampleLink.addEventListener('click', (e) => {
        e.preventDefault();
        showMCPExample();
      });
    }

    // Preset buttons
    const presetButtons = document.querySelectorAll('.preset-btn');
    presetButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        const preset = e.currentTarget.dataset.preset;
        addMCPPreset(preset);
      });
    });

    // Create MCP info modal
    createMCPInfoModal();

    // Initial validation
    validateMCPConfig();
  };

  // Validate MCP JSON configuration
  const validateMCPConfig = () => {
    const mcpConfig = document.getElementById('mcpConfig');
    const mcpConfigStatus = document.getElementById('mcpConfigStatus');
    
    if (!mcpConfig || !mcpConfigStatus) return;

    const configText = mcpConfig.value.trim();
    
    if (!configText || configText === '[]') {
      mcpConfig.className = 'form-control mcp-config-textarea';
      mcpConfigStatus.textContent = '配置为空';
      mcpConfigStatus.className = 'mcp-status-text';
      return true;
    }

    try {
      const parsed = JSON.parse(configText);
      
      if (!Array.isArray(parsed)) {
        throw new Error('配置必须是一个数组');
      }

      // Validate each server config
      const errors = [];
      parsed.forEach((server, index) => {
        if (!server.name) {
          errors.push(`第 ${index + 1} 个服务器：缺少 name`);
        }
        if (!server.command && !server.connection_url) {
          errors.push(`第 ${index + 1} 个服务器：缺少 command 或 connection_url`);
        }
      });

      if (errors.length > 0) {
        throw new Error(errors.join('; '));
      }

      mcpConfig.className = 'form-control mcp-config-textarea valid';
      mcpConfigStatus.textContent = `JSON 格式正确 ✓（${parsed.length} 个服务器）`;
      mcpConfigStatus.className = 'mcp-status-text valid';
      return true;

    } catch (error) {
      mcpConfig.className = 'form-control mcp-config-textarea invalid';
      mcpConfigStatus.textContent = `JSON 无效：${error.message}`;
      mcpConfigStatus.className = 'mcp-status-text invalid';
      return false;
    }
  };

  // Format MCP JSON configuration
  const formatMCPConfig = () => {
    const mcpConfig = document.getElementById('mcpConfig');
    if (!mcpConfig) return;

    try {
      const parsed = JSON.parse(mcpConfig.value.trim() || '[]');
      mcpConfig.value = JSON.stringify(parsed, null, 2);
      validateMCPConfig();
      showToast('JSON 格式化成功！');
    } catch (error) {
      showToast('无法格式化无效的 JSON');
    }
  };

  // Show MCP configuration example
  const showMCPExample = () => {
    const exampleConfig = [
      {
        "name": "github",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {
          "GITHUB_PERSONAL_ACCESS_TOKEN": "your_github_token_here"
        }
      },
      {
        "name": "filesystem",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/directory"],
        "env": {}
      }
    ];

    const mcpConfig = document.getElementById('mcpConfig');
    if (mcpConfig) {
      mcpConfig.value = JSON.stringify(exampleConfig, null, 2);
      validateMCPConfig();
      showToast('示例配置已载入！');
    }
  };

  // Update retriever configuration for MCP
  const updateRetrieverForMCP = (enableMCP) => {
    if (enableMCP) {
      showToast('MCP 已启用——将纳入研究流程');
    } else {
      showToast('MCP 已禁用——仅使用网络搜索');
    }
  };

  // Show MCP information modal
  const showMCPInfo = () => {
    const modal = document.getElementById('mcpInfoModal');
    if (modal) {
      modal.classList.add('visible');
    }
  };

  // Create MCP info modal
  const createMCPInfoModal = () => {
    if (document.getElementById('mcpInfoModal')) return;

    const modal = document.createElement('div');
    modal.id = 'mcpInfoModal';
    modal.className = 'mcp-info-modal';
    
    modal.innerHTML = `
      <div class="mcp-info-content">
        <button class="mcp-info-close" onclick="closeMCPInfo()">
          <i class="fas fa-times"></i>
        </button>
        <h3>模型上下文协议（MCP）</h3>
        <p>MCP 让 GPT Researcher 能通过统一协议连接外部工具和数据源。</p>

        <h4 class="highlight">能带来什么：</h4>
        <ul>
          <li><span class="highlight">访问本地数据：</span> 连接数据库、文件系统和 API</li>
          <li><span class="highlight">使用外部工具：</span> 接入网络服务和第三方工具</li>
          <li><span class="highlight">扩展能力：</span> 通过 MCP 服务器添加自定义功能</li>
          <li><span class="highlight">保障安全：</span> 通过身份验证控制访问权限</li>
        </ul>

        <h4 class="highlight">快速上手：</h4>
        <ul>
          <li>勾选上方的复选框启用 MCP</li>
          <li>点击预设，把预配置的服务器加入 JSON</li>
          <li>或粘贴你自己的 MCP 配置（JSON 数组）</li>
          <li>开始研究——MCP 会以最优设置自动运行</li>
        </ul>

        <h4 class="highlight">配置格式：</h4>
        <p>每个 MCP 服务器都是一个 JSON 对象，包含以下属性：</p>
        <ul>
          <li><span class="highlight">name:</span> 唯一标识符（如 "github"、"filesystem"）</li>
          <li><span class="highlight">command:</span> 启动服务器的命令（如 "npx"、"python"）</li>
          <li><span class="highlight">args:</span> 参数数组（如 ["-y", "@modelcontextprotocol/server-github"]）</li>
          <li><span class="highlight">env:</span> 环境变量对象（如 {"API_KEY": "your_key"}）</li>
        </ul>
      </div>
    `;

    document.body.appendChild(modal);

    // Close modal when clicking outside
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        modal.classList.remove('visible');
      }
    });

    // Close with Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('visible')) {
        modal.classList.remove('visible');
      }
    });
  };

  // Close MCP info modal
  window.closeMCPInfo = () => {
    const modal = document.getElementById('mcpInfoModal');
    if (modal) {
      modal.classList.remove('visible');
    }
  };

  // Add MCP preset configurations
  const addMCPPreset = (preset) => {
    const presets = {
      github: {
        "name": "github",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {
          "GITHUB_PERSONAL_ACCESS_TOKEN": "your_github_token_here"
        }
      },
      tavily: {
        "name": "tavily",
        "command": "npx",
        "args": ["-y", "tavily-mcp@0.1.2"],
        "env": {
          "TAVILY_API_KEY": "your_tavily_api_key_here"
        }
      },
      filesystem: {
        "name": "filesystem",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/directory"],
        "env": {}
      }
    };

    const config = presets[preset];
    if (!config) return;

    const mcpConfig = document.getElementById('mcpConfig');
    if (!mcpConfig) return;

    try {
      let currentConfig = [];
      const currentText = mcpConfig.value.trim();
      
      if (currentText && currentText !== '[]') {
        currentConfig = JSON.parse(currentText);
      }

      // Check if server already exists
      const existingIndex = currentConfig.findIndex(server => server.name === config.name);
      
      if (existingIndex !== -1) {
        // Replace existing server
        currentConfig[existingIndex] = config;
        showToast(`已更新 ${preset} MCP 服务器配置`);
      } else {
        // Add new server
        currentConfig.push(config);
        showToast(`已添加 ${preset} MCP 服务器配置`);
      }

      mcpConfig.value = JSON.stringify(currentConfig, null, 2);
      validateMCPConfig();

    } catch (error) {
      console.error('Error adding preset:', error);
      showToast('添加预设配置失败');
    }
  };

  // Collect MCP configuration data
  const collectMCPData = () => {
    const mcpEnabled = document.getElementById('mcpEnabled');
    if (!mcpEnabled || !mcpEnabled.checked) {
      return null;
    }

    const mcpConfig = document.getElementById('mcpConfig');
    
    if (!mcpConfig) {
      console.warn('MCP config element not found for data collection');
      return null;
    }

    // Validate configuration before collecting
    if (!validateMCPConfig()) {
      showToast('MCP 配置无效——请先修正错误再提交');
      return null;
    }

    try {
      const configText = mcpConfig.value.trim();
      const mcpConfigs = configText && configText !== '[]' ? JSON.parse(configText) : [];

      return {
        mcp_enabled: true,
        mcp_strategy: "fast", // Always use "fast" strategy as default
        mcp_configs: mcpConfigs
      };
    } catch (error) {
      console.error('Error collecting MCP data:', error);
      showToast('处理 MCP 配置失败');
      return null;
    }
  };

  return {
    init,
    startResearch,
    copyToClipboard,
    checkCookieStatus,
    exportHistory,
    importHistory: triggerImportHistory,  // Add import function to return object
    initChat,
    sendChatMessage,
    addChatMessage
  }
})()

window.addEventListener('DOMContentLoaded', GPTResearcher.init)
