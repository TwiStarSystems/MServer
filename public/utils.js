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
  
  // Add CSRF token for state-changing requests
  const method = options.method?.toUpperCase() || 'GET';
  if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
    if (window.csrfToken && !options.headers['X-CSRF-Token']) {
      options.headers['X-CSRF-Token'] = window.csrfToken;
    }
  }
  
  // Add Content-Type if body is present and not FormData
  if (options.body && !(options.body instanceof FormData)) {
    if (!options.headers['Content-Type']) {
      options.headers['Content-Type'] = 'application/json';
    }
  }
  
  const response = await fetch(url, options);
  
  // Check for authentication errors
  if (response.status === 401 && !url.includes('/api/auth/')) {
    window.location.href = '/login.html';
    throw new Error('Authentication required');
  }
  
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
  
  return data;
}
