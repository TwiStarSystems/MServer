/**
 * MServerController - Shared Utility Functions
 *
 * This file contains common utility functions used across multiple pages.
 * Include this file before page-specific JavaScript files.
 */

/**
 * Format bytes into human-readable string
 * @param {number} bytes - The number of bytes
 * @returns {string} Formatted string (e.g., "1.5 GB")
 */
function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

/**
 * Escape HTML special characters to prevent XSS
 * @param {string} text - The text to escape
 * @returns {string} HTML-escaped text
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Global CSRF token (shared across all pages)
 */
window.csrfToken = null;

/**
 * Fetch CSRF token from server
 * @returns {Promise<boolean>} True if successful
 */
async function fetchCSRFToken() {
  try {
    // Use window.fetch directly (before wrapper is applied) or store original fetch
    const fetchFunc = window.originalFetch || window.fetch;
    const response = await fetchFunc('/api/csrf-token');
    if (response.ok) {
      const data = await response.json();
      window.csrfToken = data.csrf_token;
      return true;
    }
  } catch (err) {
    console.error('Failed to fetch CSRF token:', err);
  }
  return false;
}

/**
 * Check if the current user has a specific permission.
 * Supports wildcards: '*' matches everything, 'servers.*' matches 'servers.files.view'.
 */
function hasPermission(permission) {
  if (!window.currentUser || !window.currentUser.permissions) return false;
  const perms = window.currentUser.permissions;
  if (perms.includes('*')) return true;
  if (perms.includes(permission)) return true;
  const parts = permission.split('.');
  for (let i = 1; i < parts.length; i++) {
    const wildcard = parts.slice(0, i).join('.') + '.*';
    if (perms.includes(wildcard)) return true;
  }
  return false;
}

/**
 * Make an authenticated API request
 * @param {string} url - The API endpoint URL
 * @param {object} options - Fetch options (method, headers, body, etc.)
 * @returns {Promise<any>} The parsed JSON response
 */
async function apiRequest(url, options = {}) {
  // Set default headers
  if (!options.headers) {
    options.headers = {};
  }

  // Add Content-Type if body is present and not FormData
  // (CSRF token + 401 redirect handled by the global fetch wrapper in app.js/settings.js)
  if (options.body && !(options.body instanceof FormData)) {
    if (!options.headers['Content-Type']) {
      options.headers['Content-Type'] = 'application/json';
    }
  }

  const response = await fetch(url, options);

  // Parse response
  const contentType = response.headers.get('content-type');
  let data;

  if (contentType && contentType.includes('application/json')) {
    data = await response.json();
  } else {
    data = await response.text();
  }

  if (!response.ok) {
    throw new Error(data.error || data.message || `HTTP ${response.status}`);
  }

  // Auto-handle pending approval responses
  if (data && data.pending === true && data.message) {
    if (typeof showNotification === 'function') {
      showNotification(data.message, 'info');
    }
  }

  return data;
}

/**
 * Show a notification toast message
 * @param {string} message - The message to display
 * @param {string} type - The type of notification (info, success, warning, error)
 */
function showNotification(message, type = 'info') {
  // Remove existing notification
  const existing = document.querySelector('.notification');
  if (existing) existing.remove();
  
  const notification = document.createElement('div');
  notification.className = `notification notification-${type}`;
  notification.innerHTML = `
    <span class="notification-message">${escapeHtml(message)}</span>
    <button class="notification-close" onclick="this.parentElement.remove()">&times;</button>
  `;
  
  document.body.appendChild(notification);
  
  // Auto-remove after 5 seconds
  setTimeout(() => {
    if (notification.parentElement) {
      notification.remove();
    }
  }, 5000);
}
