/**
 * VSIX Packaging Script for Amprealize Extension
 *
 * Creates a production-ready VSIX package for the VS Code Marketplace
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vsce = require('@vscode/vsce');

async function packageExtension() {
    console.log('🚀 Starting Amprealize Extension packaging...');

    try {
        // Ensure we're in the extension directory
        process.chdir(path.join(__dirname, '..'));

        // Clean previous builds
        console.log('🧹 Cleaning previous builds...');
        if (fs.existsSync('out')) {
            fs.rmSync('out', { recursive: true, force: true });
        }
        if (fs.existsSync('dist')) {
            fs.rmSync('dist', { recursive: true, force: true });
        }

        // Compile TypeScript
        console.log('📦 Compiling TypeScript...');
        execSync('npm run compile', { stdio: 'inherit' });

        // Check for .vscode/launch.json
        if (!fs.existsSync('.vscode/launch.json')) {
            console.log('⚙️  Creating VS Code launch configuration...');
            fs.mkdirSync('.vscode', { recursive: true });
            fs.writeFileSync('.vscode/launch.json', JSON.stringify({
                version: '0.2.0',
                configurations: [
                    {
                        name: 'Run Extension',
                        type: 'extensionHost',
                        request: 'launch',
                        args: [
                            '--extensionDevelopmentPath=${workspaceFolder}'
                        ],
                        outFiles: [
                            '${workspaceFolder}/out/**/*.js'
                        ],
                        preLaunchTask: 'npm: compile'
                    },
                    {
                        name: 'Extension Tests',
                        type: 'extensionHost',
                        request: 'launch',
                        args: [
                            '--extensionDevelopmentPath=${workspaceFolder}',
                            '--extensionTestsPath=${workspaceFolder}/out/test/suite/index'
                        ],
                        outFiles: [
                            '${workspaceFolder}/out/test/**/*.js'
                        ],
                        preLaunchTask: 'npm: compile'
                    }
                ]
            }, null, 2));
        }

        // Create VSIX package
        console.log('📦 Creating VSIX package...');
        const vsixPath = await vsce.createVSIX({
            cwd: process.cwd(),
            packagePath: './dist',
            packageMicrosoftVSCode: false
        });

        console.log(`✅ VSIX package created successfully: ${vsixPath}`);

        // Create release notes
        const releaseNotes = generateReleaseNotes();
        fs.writeFileSync('./dist/RELEASE_NOTES.md', releaseNotes);

        console.log('📝 Release notes generated');
        console.log('🎉 Packaging complete!');

    } catch (error) {
        console.error('❌ Packaging failed:', error.message);
        process.exit(1);
    }
}

function generateReleaseNotes() {
    const date = new Date().toISOString().split('T')[0];
    return `# Amprealize IDE Extension v0.0.1 (${date})

## ✨ What's New

### Epic 5.4: Execution Tracker View
- ✅ Real-time workflow run monitoring
- ✅ Interactive run status display with progress indicators
- ✅ Error/warning highlights and detailed run information
- ✅ Run detail panel with timeline and metrics

### Epic 5.5: Compliance Review Panel
- ✅ Interactive compliance checklist interface
- ✅ Step-by-step validation workflow
- ✅ Evidence attachment and comment system
- ✅ Progress tracking and approval workflow

### Epic 5.6: Authentication Flows
- ✅ OAuth2 device flow implementation
- ✅ Token management and automatic refresh
- ✅ Session status indicators
- ✅ Secure credential storage

### Epic 5.7: Settings Sync
- ✅ Cloud settings storage and synchronization
- ✅ Settings import/export functionality
- ✅ Team settings inheritance
- ✅ Configuration conflict resolution

### Epic 5.8: Keyboard Shortcuts
- ✅ Quick actions palette for common operations
- ✅ Keyboard shortcuts for key features
- ✅ Command integration and context menus

### Epic 5.9: VSIX Packaging & Marketplace
- ✅ Automated packaging scripts
- ✅ Production-ready configuration
- ✅ Marketplace publishing setup

## 🛠️ Installation

### From VS Code
1. Open VS Code
2. Go to Extensions (Ctrl+Shift+X)
3. Search for "Amprealize"
4. Click Install

### From VSIX
1. Download the VSIX file
2. Run: \`code --install-extension amprealize-ide-extension-0.0.1.vsix\`

## 🔧 Configuration

After installation, configure the extension:

1. Go to Settings (Ctrl+,)
2. Search for "Amprealize"
3. Configure:
   - **Python Path**: Path to Python executable
   - **CLI Path**: Path to amprealize command
   - **API Base URL**: Backend API endpoint
   - **Timeout**: Request timeout in milliseconds

## 🚀 Quick Start

1. **Sign In**: Use \`Amprealize: Sign In\` command
2. **View Runs**: Check the "Execution Tracker" in Explorer
3. **Review Compliance**: Access "Compliance Tracker" in Explorer
4. **Quick Actions**: Use \`Ctrl+Shift+P\` → "Amprealize: Quick Actions"

## 📋 Available Commands

- \`Amprealize: Refresh Execution Tracker\`
- \`Amprealize: View Run Details\`
- \`Amprealize: Refresh Compliance Tracker\`
- \`Amprealize: Open Compliance Review\`
- \`Amprealize: Sign In\`
- \`Amprealize: Sign Out\`
- \`Amprealize: Auth Status\`
- \`Amprealize: Settings Sync\`
- \`Amprealize: Settings Export\`
- \`Amprealize: Settings Import\`
- \`Amprealize: Quick Actions\`

## 🐛 Known Issues

- None at this time

## 📝 Changelog

See GitHub releases for detailed changelog.

## 💬 Support

For issues and feature requests, please visit our GitHub repository.

---
*Generated by Amprealize Extension packaging script*
`;
}

// Run if called directly
if (require.main === module) {
    packageExtension();
}

module.exports = { packageExtension };
