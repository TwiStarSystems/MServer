// Public status page JavaScript

document.addEventListener('DOMContentLoaded', () => {
    loadServers();
    
    // Auto-refresh every 30 seconds
    setInterval(loadServers, 30000);
});

async function loadServers() {
    const container = document.getElementById('servers-container');
    
    try {
        const response = await fetch('/api/public/servers');
        const data = await response.json();
        
        if (data.servers && data.servers.length > 0) {
            container.innerHTML = data.servers.map(server => createServerCard(server)).join('');
        } else {
            container.innerHTML = `
                <div class="no-servers">
                    <h3>No Servers Available</h3>
                    <p>There are currently no servers to display.</p>
                </div>
            `;
        }
        
        // Update last updated time
        document.getElementById('last-updated').textContent = 
            `Last updated: ${new Date().toLocaleTimeString()}`;
            
    } catch (err) {
        container.innerHTML = `
            <div class="no-servers">
                <h3>Unable to Load Servers</h3>
                <p>Please try again later.</p>
            </div>
        `;
    }
}

function createServerCard(server) {
    const statusClass = server.running ? 'online' : 'offline';
    const statusText = server.running ? 'Online' : 'Offline';
    
    // Get server type display name
    const serverTypes = {
        'vanilla': 'Vanilla',
        'bedrock': 'Bedrock',
        'paper': 'Paper',
        'folia': 'Folia',
        'purpur': 'Purpur',
        'forge': 'Forge',
        'neoforge': 'NeoForge'
    };
    
    const typeDisplay = escapeHtml(serverTypes[server.serverType] || server.serverType || 'Unknown');
    const versionDisplay = escapeHtml(server.version || 'N/A');
    
    return `
        <div class="server-card">
            <div class="server-name">${escapeHtml(server.name)}</div>
            <div class="server-type">${typeDisplay} Server</div>
            <div class="server-status">
                <div class="status-indicator ${statusClass}"></div>
                <span class="status-text ${statusClass}">${statusText}</span>
            </div>
            <div class="server-info">
                <div class="info-row">
                    <span class="info-label">Version</span>
                    <span class="info-value">${versionDisplay}</span>
                </div>
                ${server.port ? `
                <div class="info-row">
                    <span class="info-label">Port</span>
                    <span class="info-value">${server.port}</span>
                </div>
                ` : ''}
            </div>
        </div>
    `;
}
// Note: escapeHtml is in utils.js
