# Cross-IDE Testing Framework Design

> **Comprehensive Testing Strategy for VSCode, Cursor, and Claude Desktop**
> **Status:** Phase 4 Implementation
> **Updated:** 2025-11-07

## Executive Summary

The Cross-IDE Testing Framework ensures **100% feature parity** and **reliable performance** across VSCode, Cursor, and Claude Desktop platforms. Built on the existing test infrastructure, this framework provides **automated validation** of all Amprealize features across multiple IDE environments.

## Framework Architecture

### Testing Philosophy

**🧪 Multi-Layer Testing Strategy:**

1. **Unit Tests**: Individual components and functions
2. **Integration Tests**: Service-to-service communication
3. **Extension Tests**: IDE-specific functionality
4. **Cross-Platform Tests**: Feature parity validation
5. **Performance Tests**: Load and stress testing
6. **E2E Tests**: Complete user workflows

### Framework Components

```
tests/
├── unit/                    # Unit tests (existing)
├── integration/             # Service integration (existing)
├── extension/               # IDE extension tests
│   ├── vscode/             # VSCode extension tests
│   ├── cursor/             # Cursor extension tests
│   └── claude/             # Claude Desktop MCP tests
├── cross-ide/              # Cross-platform validation
│   ├── feature-parity/     # Feature parity tests
│   ├── authentication/     # Auth flow tests
│   └── performance/        # Performance benchmarks
├── e2e/                    # End-to-end workflows
└── utils/                  # Testing utilities
```

## Existing Test Infrastructure Analysis

### ✅ What's Already Available

**Service-Level Tests:**
- **450+ tests** across all services (parity tests, integration tests)
- **MCP Protocol Tests** (4/4 passing)
- **Cross-Surface Tests** (11/11 passing)
- **Device Flow Tests** (28 tests passing)

**Extension Tests:**
- **VSCode Extension** runtime validation (Extension Development Host)
- **Extension compilation** and packaging tests
- **Build system** validation (webpack, TypeScript)

**CI/CD Integration:**
- **test-extension** job validates VSCode extension builds
- **MCP server validation** tests protocol compliance
- **Security scanning** prevents credential leaks

### 🔄 What Needs Extension

**Missing Components:**
- Cursor extension testing framework
- Claude Desktop MCP testing
- Cross-platform feature parity validation
- Performance benchmarking across IDEs
- Automated IDE-specific tests

## Cross-IDE Testing Framework Design

### 1. Extension-Specific Testing

#### VSCode Extension Tests
```typescript
// tests/extension/vscode/extension.test.ts
import * as vscode from 'vscode';
import { AmprealizeClient } from '../../../extension/src/client/AmprealizeClient';
import { BehaviorTreeDataProvider } from '../../../extension/src/providers/BehaviorTreeDataProvider';

describe('VSCode Extension', () => {
  let extension: vscode.Extension<any>;
  let client: AmprealizeClient;

  beforeAll(async () => {
    extension = await vscode.extensions.getExtension('amprealize.amprealize-ide-extension')?.activate();
    client = extension.exports.client;
  });

  describe('Activation', () => {
    it('should activate successfully', () => {
      expect(extension).toBeDefined();
      expect(extension.isActive).toBe(true);
    });
  });

  describe('Commands', () => {
    it('should register all 7 commands', async () => {
      const commands = await vscode.commands.getCommands(true);
      const amprealizeCommands = commands.filter(cmd => cmd.startsWith('amprealize.'));
      expect(amprealizeCommands).toHaveLength(7);
    });
  });

  describe('Tree Views', () => {
    it('should create behavior tree provider', () => {
      const treeProvider = vscode.window.createTreeView('amprealize.executionTracker');
      expect(treeProvider).toBeDefined();
    });
  });
});
```

#### Cursor Extension Tests
```typescript
// tests/extension/cursor/extension.test.ts
import * as cursor from 'cursor-api';
import { AmprealizeClient } from '../../../cursor-extension/src/client/AmprealizeClient';

describe('Cursor Extension', () => {
  let extension: cursor.Extension<any>;

  beforeAll(async () => {
    extension = await cursor.extensions.getExtension('amprealize.amprealize-cursor-extension')?.activate();
  });

  describe('MCP Integration', () => {
    it('should connect to MCP server', async () => {
      const mcpStatus = await extension.exports.mcpClient.status();
      expect(mcpStatus.connected).toBe(true);
    });
  });

  describe('AI Feature Compatibility', () => {
    it('should not conflict with Cursor AI', () => {
      const cursorAI = extension.exports.getCursorAICompatibility();
      expect(cursorAI.compatible).toBe(true);
    });
  });
});
```

#### Claude Desktop MCP Tests
```typescript
// tests/extension/claude/mcp.test.ts
import { spawn } from 'child_process';

describe('Claude Desktop MCP Integration', () => {
  let mcpServer: any;

  beforeAll(() => {
    mcpServer = spawn('python', ['-m', 'amprealize.mcp_server'], {
      env: { ...process.env, AMPREALIZE_MCP_PORT: '3001' }
    });
  });

  afterAll(() => {
    if (mcpServer) {
      mcpServer.kill();
    }
  });

  describe('MCP Protocol', () => {
    it('should respond to initialize', async () => {
      const response = await sendMCPRequest('initialize', {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: { name: 'claude-desktop', version: '1.0.0' }
      });
      expect(response.result.protocolVersion).toBe('2024-11-05');
    });

    it('should list available tools', async () => {
      const response = await sendMCPRequest('tools/list');
      expect(response.result.tools).toHaveLength(64);
    });
  });
});
```

### 2. Cross-Platform Feature Parity

#### Feature Parity Tests
```typescript
// tests/cross-ide/feature-parity/behavior-management.test.ts
describe('Behavior Management Feature Parity', () => {
  const testBehavior = {
    name: 'test-parity-behavior',
    instruction: 'Test behavior for cross-platform validation',
    role: 'strategist'
  };

  [Platform.VSCODE, Platform.CURSOR, Platform.CLAUDE].forEach(platform => {
    describe(`${platform} Platform`, () => {
      it('should list behaviors', async () => {
        const behaviors = await platform.getBehaviors();
        expect(Array.isArray(behaviors)).toBe(true);
        expect(behaviors.length).toBeGreaterThan(0);
      });

      it('should create behavior', async () => {
        const behavior = await platform.createBehavior(testBehavior);
        expect(behavior.name).toBe(testBehavior.name);
        expect(behavior.role).toBe(testBehavior.role);
      });

      it('should search behaviors', async () => {
        const results = await platform.searchBehaviors('test');
        expect(results.length).toBeGreaterThan(0);
      });
    });
  });
});
```

#### Authentication Flow Tests
```typescript
// tests/cross-ide/authentication/device-flow.test.ts
describe('Device Flow Authentication Parity', () => {
  [Platform.VSCODE, Platform.CURSOR, Platform.CLAUDE].forEach(platform => {
    describe(`${platform} Auth Flow`, () => {
      it('should initiate device flow', async () => {
        const flow = await platform.initiateAuthFlow();
        expect(flow.deviceCode).toBeDefined();
        expect(flow.verificationUri).toBeDefined();
        expect(flow.userCode).toBeDefined();
      });

      it('should handle token exchange', async () => {
        // Simulate user authorization
        const token = await platform.exchangeCode('test-device-code');
        expect(token.accessToken).toBeDefined();
        expect(token.refreshToken).toBeDefined();
      });

      it('should persist tokens', async () => {
        const persisted = await platform.getStoredToken();
        expect(persisted.accessToken).toBeDefined();
      });
    });
  });
});
```

### 3. Performance Benchmarking

#### Performance Tests
```typescript
// tests/cross-ide/performance/benchmark.test.ts
describe('Cross-IDE Performance Benchmarks', () => {
  [Platform.VSCODE, Platform.CURSOR, Platform.CLAUDE].forEach(platform => {
    describe(`${platform} Performance`, () => {
      it('should load extension within 2 seconds', async () => {
        const startTime = performance.now();
        await platform.activateExtension();
        const loadTime = performance.now() - startTime;
        expect(loadTime).toBeLessThan(2000);
      });

      it('should respond to commands within 100ms', async () => {
        const startTime = performance.now();
        await platform.executeCommand('behaviors list');
        const responseTime = performance.now() - startTime;
        expect(responseTime).toBeLessThan(100);
      });

      it('should handle concurrent requests', async () => {
        const requests = Array(10).fill(0).map(() => platform.getBehaviors());
        const results = await Promise.all(requests);
        expect(results.every(result => Array.isArray(result))).toBe(true);
      });
    });
  });
});
```

### 4. End-to-End Workflow Tests

#### E2E Workflow Tests
```typescript
// tests/e2e/workflow-execution.test.ts
describe('End-to-End Workflow Execution', () => {
  [Platform.VSCODE, Platform.CURSOR, Platform.CLAUDE].forEach(platform => {
    describe(`${platform} E2E Workflow`, () => {
      it('should execute complete workflow from template', async () => {
        // 1. List available templates
        const templates = await platform.listWorkflowTemplates();
        expect(templates.length).toBeGreaterThan(0);

        // 2. Select template and execute
        const run = await platform.executeWorkflow(templates[0].id);
        expect(run.id).toBeDefined();

        // 3. Monitor execution
        const completed = await platform.waitForCompletion(run.id, 30000);
        expect(completed.status).toBe('completed');

        // 4. Validate results
        const results = await platform.getWorkflowResults(run.id);
        expect(results.output).toBeDefined();
      });
    });
  });
});
```

## Testing Automation Framework

### 1. Test Environment Management

```typescript
// tests/utils/environment-manager.ts
export class TestEnvironmentManager {
  private containers: Map<string, any> = new Map();

  async setupTestEnvironment(): Promise<void> {
    // Start test databases
    await this.startPostgreSQLContainers();
    await this.startRedisContainer();
    await this.startAmprealizeServices();

    // Setup IDE test environments
    await this.setupVSCodeTestEnvironment();
    await this.setupCursorTestEnvironment();
    await this.setupClaudeTestEnvironment();
  }

  async cleanupTestEnvironment(): Promise<void> {
    // Stop all containers
    for (const container of this.containers.values()) {
      await container.stop();
    }
    this.containers.clear();
  }
}
```

### 2. Platform Abstraction

```typescript
// tests/utils/platform-abstraction.ts
export interface TestingPlatform {
  name: Platform;
  activateExtension(): Promise<void>;
  executeCommand(command: string, args?: any[]): Promise<any>;
  getBehaviors(): Promise<any[]>;
  createBehavior(behavior: any): Promise<any>;
  searchBehaviors(query: string): Promise<any[]>;
  initiateAuthFlow(): Promise<any>;
  exchangeCode(code: string): Promise<any>;
  getStoredToken(): Promise<any>;
  listWorkflowTemplates(): Promise<any[]>;
  executeWorkflow(templateId: string): Promise<any>;
}

export class VSCodePlatform implements TestingPlatform {
  // VSCode-specific implementation
}

export class CursorPlatform implements TestingPlatform {
  // Cursor-specific implementation
}

export class ClaudePlatform implements TestingPlatform {
  // Claude Desktop-specific implementation
}
```

### 3. Test Data Management

```typescript
// tests/utils/test-data-manager.ts
export class TestDataManager {
  async seedTestData(): Promise<void> {
    // Create test behaviors
    const behaviors = [
      { name: 'test-strategist', role: 'strategist', instruction: 'Test strategist behavior' },
      { name: 'test-student', role: 'student', instruction: 'Test student behavior' },
      { name: 'test-teacher', role: 'teacher', instruction: 'Test teacher behavior' }
    ];

    for (const behavior of behaviors) {
      await this.createTestBehavior(behavior);
    }

    // Create test workflows
    const workflows = [
      { name: 'test-workflow-1', description: 'Test workflow 1' },
      { name: 'test-workflow-2', description: 'Test workflow 2' }
    ];

    for (const workflow of workflows) {
      await this.createTestWorkflow(workflow);
    }
  }

  async cleanupTestData(): Promise<void> {
    // Clean up all test data
  }
}
```

## CI/CD Integration

### GitHub Actions Workflow

```yaml
# .github/workflows/cross-ide-tests.yml
name: Cross-IDE Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM

jobs:
  cross-ide-validation:
    name: Cross-IDE Validation
    runs-on: ubuntu-latest

    strategy:
      matrix:
        platform: [vscode, cursor, claude]

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up test environment
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,postgres,telemetry,semantic]"
          docker-compose -f docker-compose.test.yml up -d

      - name: Run platform-specific tests
        run: |
          npm install
          npm test -- --platform=${{ matrix.platform }}

      - name: Run cross-platform parity tests
        run: |
          pytest tests/cross-ide/ -v

      - name: Performance benchmarks
        run: |
          pytest tests/cross-ide/performance/ -v --benchmark-only

      - name: Upload test results
        uses: actions/upload-artifact@v4
        with:
          name: test-results-${{ matrix.platform }}
          path: test-results/
```

### Automated Test Execution

```bash
#!/bin/bash
# scripts/run-cross-ide-tests.sh

set -e

echo "🧪 Running Cross-IDE Test Suite"

# Setup test environment
./scripts/setup-test-environment.sh

# Run unit tests
echo "Running unit tests..."
pytest tests/unit/ -v

# Run integration tests
echo "Running integration tests..."
pytest tests/integration/ -v

# Run extension tests
echo "Running VSCode extension tests..."
cd extension && npm test

# Run cross-platform tests
echo "Running cross-platform tests..."
pytest tests/cross-ide/ -v

# Run E2E tests
echo "Running end-to-end tests..."
pytest tests/e2e/ -v

# Generate test report
echo "Generating test report..."
./scripts/generate-test-report.sh

echo "✅ Cross-IDE tests completed"
```

## Test Coverage & Metrics

### Coverage Targets

| Test Type | Coverage Target | Current Status |
|-----------|----------------|----------------|
| **Unit Tests** | 90%+ | ✅ 85% |
| **Integration Tests** | 95%+ | ✅ 90% |
| **Extension Tests** | 80%+ | 🔄 60% |
| **Cross-Platform Tests** | 100% | ⏳ 0% |
| **Performance Tests** | All hot paths | ⏳ 0% |
| **E2E Tests** | Critical workflows | ⏳ 0% |

### Performance Benchmarks

| Metric | Target | Current |
|--------|--------|---------|
| **Extension Load Time** | <2s | VSCode: 1.2s |
| **Command Response Time** | <100ms | Varies by command |
| **Memory Usage** | <50MB | VSCode: 32MB |
| **CPU Usage** | <5% | Idle: 1% |

### Quality Gates

**✅ Pass Criteria:**
- All unit tests pass
- All integration tests pass
- Extension activation successful on all platforms
- Feature parity validated across all platforms
- Performance benchmarks meet targets
- E2E workflows complete successfully

**❌ Fail Criteria:**
- Any test failure
- Performance regression >10%
- Memory leak detected
- Authentication flow broken
- Critical feature not available on any platform

## Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [ ] Set up test environment management
- [ ] Create platform abstraction layer
- [ ] Implement basic extension tests for VSCode
- [ ] Add Cursor extension testing framework

### Phase 2: Feature Parity (Week 2)
- [ ] Implement cross-platform feature tests
- [ ] Add authentication flow tests
- [ ] Create performance benchmarking suite
- [ ] Set up automated CI/CD integration

### Phase 3: E2E Validation (Week 3)
- [ ] Build comprehensive E2E test suite
- [ ] Add Claude Desktop MCP testing
- [ ] Implement test data management
- [ ] Create test reporting and analytics

### Phase 4: Automation (Week 4)
- [ ] Integrate with existing CI/CD pipeline
- [ ] Set up nightly test runs
- [ ] Add performance monitoring and alerting
- [ ] Create test documentation and runbooks

## Risk Assessment

### High Risk
- **IDE Environment Stability**: CI/CD runner limitations for GUI testing
- **Extension Loading**: Async activation and timing issues
- **Authentication Flow**: Device flow testing complexity

### Medium Risk
- **Performance Testing**: Consistency across different hardware
- **Cross-Platform Issues**: Platform-specific differences
- **MCP Integration**: Protocol compliance validation

### Low Risk
- **Unit Tests**: Well-established patterns
- **Integration Tests**: Existing infrastructure
- **CI/CD Integration**: Proven workflows

## Success Metrics

### Technical Metrics
- **Test Coverage**: 90%+ across all test types
- **Pass Rate**: 99%+ for automated tests
- **Performance**: Meet all benchmark targets
- **Reliability**: Zero flaky tests

### Business Metrics
- **Feature Parity**: 100% across all platforms
- **User Experience**: <2s load times
- **Developer Productivity**: Fast feedback loops
- **Quality Assurance**: Automated validation

## Conclusion

The Cross-IDE Testing Framework provides **comprehensive validation** of Amprealize features across VSCode, Cursor, and Claude Desktop platforms. By building on existing test infrastructure and adding platform-specific testing, we ensure **reliable, high-quality** extensions for all supported IDEs.

**Key Benefits:**
- **Automated Quality Assurance** across all platforms
- **Early Detection** of cross-platform issues
- **Performance Validation** and benchmarking
- **Continuous Integration** with existing workflows

**Next Steps:**
1. Implement Phase 1 foundation testing
2. Set up cross-platform test environments
3. Begin feature parity validation
4. Integrate with CI/CD pipeline

---

*Framework Design: 2025-11-07*
*Ready for Implementation: Epic 6.5 Phase 4*
