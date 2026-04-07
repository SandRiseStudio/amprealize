# Amprealize Homebrew Formula
#
# Usage:
#   1. Create a tap repository: github.com/<org>/homebrew-amprealize
#   2. Copy this formula to Formula/amprealize.rb in the tap
#   3. After tapping: brew install amprealize
#
# Or install directly from PyPI:
#   brew install python@3.11
#   pip install amprealize

class Amprealize < Formula
  include Language::Python::Virtualenv

  desc "Amprealize developer tooling and task orchestration"
  homepage "https://amprealize.ai"
  url "https://files.pythonhosted.org/packages/3f/eb/777ee881ea777a0fe1a838ef99cd0449b59b89ef4a274c6bf5573c6caf15/amprealize-0.1.0.tar.gz"
  sha256 "ccfc75ded83260f2fdad0bfcdd5aa6cdde08bdacab28f915da0650de4bf3423c"
  license "Apache-2.0"
  head "https://github.com/SandRiseStudio/amprealize.git", branch: "main"

  depends_on "python@3.11"
  depends_on "podman" => :optional

  # Core dependencies (pinned for reproducibility)
  resource "fastapi" do
    url "https://files.pythonhosted.org/packages/7b/5e/bf0471f14bf6ebfbee8208148a3396d1a23298531a6cc10776c59f4c0f87/fastapi-0.115.0.tar.gz"
    sha256 "f93b4ca3529a8ebc6fc3fcf710e5efa8de3df9b41570958abf1d97d843138004"
  end

  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/f6/8f/3b9f7a38caa3fa0bcb3cea7ee9958e89a9a6efc0e6f51fd6096f24cac140/pydantic-2.9.0.tar.gz"
    sha256 "c7a8a9fdf7d100afa49647eae340e2d23efa382466a8d177efcd1381e9be5598"
  end

  resource "httpx" do
    url "https://files.pythonhosted.org/packages/5c/2d/3da5bdf4408b8b2800061c339f240c1802f2e82d55e50bd39c5a881f47f0/httpx-0.27.0.tar.gz"
    sha256 "a0cb88a46f32dc874e04ee956e4c2764aba2aa228f650b06788ba6bda2962ab5"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/source/c/click/click-8.1.7.tar.gz"
    sha256 "ca9853ad459e787e2192211578cc907e7594e294c7ccc834310722b41b9ca6de"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/source/p/pyyaml/pyyaml-6.0.2.tar.gz"
    sha256 "d584d9ec91ad65861cc08d42e834324ef890a082e591037abe114850ff7bbc3e"
  end

  def install
    virtualenv_install_with_resources

    # Generate shell completions
    generate_completions_from_executable(bin/"amprealize", shells: [:bash, :zsh, :fish], shell_parameter_format: :click)
  end

  def post_install
    # Create data directories
    (var/"amprealize").mkpath
    (var/"amprealize/data").mkpath
    (var/"amprealize/telemetry").mkpath
  end

  def caveats
    <<~EOS
      Amprealize has been installed!

      To get started:
        amprealize init              # Initialize a new project
        amprealize doctor            # Check installation health
        amprealize mcp-server        # Start the MCP server

      Configuration is stored in:
        ~/.amprealize/config.yaml    (user config)
        .amprealize/config.yaml      (project config)

      Data is stored in:
        #{var}/amprealize/           (Homebrew managed)

      For MCP integration with VS Code:
        Add to your VS Code settings.json:
        {
          "github.copilot.chat.mcpServers": {
            "amprealize": {
              "command": "amprealize",
              "args": ["mcp-server"]
            }
          }
        }

      Optional: Install Podman for infrastructure management:
        brew install podman
    EOS
  end

  test do
    # Test CLI is accessible
    assert_match "Amprealize", shell_output("#{bin}/amprealize --version")

    # Test doctor command (JSON output for parsing)
    output = shell_output("#{bin}/amprealize doctor --json")
    assert_match '"passed":', output

    # Test init in temp directory
    system bin/"amprealize", "init", "--non-interactive", "--template", "minimal"
    assert_predicate testpath/".amprealize/config.yaml", :exist?

    # Test Python import
    system "python3", "-c", "import amprealize; print(amprealize.__version__)"
  end
end
