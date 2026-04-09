# ~/.bash_profile - Login shell configuration

# ============================================================================
# Load .bashrc for common settings
# ============================================================================
if [ -f ~/.bashrc ]; then
    source ~/.bashrc
fi

# ============================================================================
# Starship Prompt
# ============================================================================
eval "$(starship init bash)"

# ============================================================================
# Configurable Paths (override in ~/.bashrc.local)
# ============================================================================

REPOS_DIR="${REPOS_DIR:-$HOME/repos}"

# ============================================================================
# Aliases - General
# ============================================================================

alias c='clear'
alias t='./task'

# ============================================================================
# Modern CLI Tools
# ============================================================================

# bat (better cat) - syntax highlighting
export BAT_THEME="Dracula"          # Consistent with FZF and delta
alias cat='bat --style=plain'
alias catn='bat --style=numbers'
alias catf='bat --style=full'

# eza (better ls) - git status, icons, colors
alias ls='eza --icons'
alias ll='eza -lah --icons --git'
alias la='eza -a --icons'
alias l='eza --icons'
alias lt='eza --tree --level=2 --icons'
alias tree='eza --tree --icons'

# eza tree variations (use these instead of traditional tree options)
alias tree2='eza --tree --level=2 --icons'
alias tree3='eza --tree --level=3 --icons'
alias treea='eza --tree --all --icons'              # Include hidden files
alias treel='eza --tree --long --icons'             # Long format with sizes
alias treeg='eza --tree --git-ignore --icons'       # Respect .gitignore

# ripgrep (better grep) - already installed, add convenient aliases
alias rgi='rg -i'              # Case insensitive
alias rgf='rg --files | rg'    # Find files by name
alias rgjs='rg -t js'          # Search only JS files
alias rgcs='rg -t cs'          # Search only C# files

# fd (better find) - already installed
alias fdf='fd --type f'        # Files only
alias fdd='fd --type d'        # Directories only

# zoxide (smart cd) - jump to frequently used directories
eval "$(zoxide init bash)"

# mdprint - convert any markdown file to HTML and open in browser for printing
# Usage: mdprint file.md
mdprint() {
    local out="${1%.md}.html"
    pandoc "$1" -o "$out" --standalone --metadata title="${1%.md}" \
        -c "https://cdn.jsdelivr.net/npm/github-markdown-css/github-markdown.css" \
        -V "header-includes=<style>body{background:#0d1117;padding:2rem}.markdown-body{box-sizing:border-box;min-width:200px;max-width:980px;margin:0 auto;padding:45px}</style>" \
        --metadata "pagetitle=${1%.md}" \
        -V 'include-before=<article class="markdown-body" data-color-mode="dark" data-dark-theme="dark">' \
        -V 'include-after=</article>'
    start "$out"
}

# ff - fuzzy find any file, cd to its directory
# Usage: ff [pattern]  e.g. ff experiment_base  or just: ff
ff() {
    local file
    file=$(fd ${1:-.} "$REPOS_DIR" | fzf --preview 'bat --color=always {}')
    [ -n "$file" ] && cd "$(dirname "$file")"
}

# fd - fuzzy cd into any directory under REPOS_DIR
# Usage: fcd [pattern]  e.g. fcd scores  or just: fcd
fcd() {
    local dir
    dir=$(fd --type d ${1:-.} "$REPOS_DIR" | fzf --preview 'eza -lah --icons {}')
    [ -n "$dir" ] && cd "$dir"
}

# ============================================================================
# Aliases - Docker & Containers
# ============================================================================

# Docker basics
alias d='docker'
alias dc='docker compose'           # Docker Compose v2
alias dps='docker ps --format "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}"'
alias dpsa='docker ps -a --format "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}"'
alias di='docker images'
alias dv='docker volume ls'
alias dn='docker network ls'

# Docker operations
alias dexec='docker exec -it'
alias dlogs='docker logs -f --tail 100'
alias dstop='docker stop'
alias dstart='docker start'
alias drestart='docker restart'
alias drm='docker rm -f'
alias drmi='docker rmi'

# Docker Compose
alias dcup='docker compose up -d'
alias dcdown='docker compose down'
alias dcrestart='docker compose restart'
alias dclogs='docker compose logs -f'
alias dcps='docker compose ps'
alias dcbuild='docker compose build'
alias dcpull='docker compose pull'

# Docker cleanup
alias dprune='docker system prune -af'
alias dclean='docker rm -v $(docker ps -a -q -f status=exited) 2>/dev/null; docker rmi $(docker images -f "dangling=true" -q) 2>/dev/null'
alias dvclean='docker volume prune -f'
alias dnclean='docker network prune -f'

# Modern Docker tools
alias lzd='lazydocker'              # TUI for Docker
alias ctop='ctop'                   # Container monitoring

# ============================================================================
# Aliases - Git
# ============================================================================

alias gs='git status'
alias gd='git diff'
alias gdc='git diff --cached'
alias gf='git fetch -p'
alias gfp='git fetch -p && git pull'
alias gp='git pull'
alias gb='git branch -a'
alias grl='git reflog'
alias gpl='git log --abbrev-commit --pretty=oneline'
alias glog='git log --graph --oneline --decorate --all'
alias gls='git log --oneline --decorate -20'
alias gundo='git reset --soft HEAD~1'

# ============================================================================
# Aliases - VS Code
# ============================================================================

# ============================================================================
# Functions - Git
# ============================================================================

# Checkout existing branch
gc() {
    if [ -z "$1" ]; then
        echo "Usage: gc <branch-name>"
        return 1
    fi
    git checkout "$1"
}

# Checkout new branch
gcb() {
    if [ -z "$1" ]; then
        echo "Usage: gcb <new-branch-name>"
        return 1
    fi
    git checkout -b "$1"
}

# Quick commit with message
gcm() {
    if [ -z "$1" ]; then
        echo "Usage: gcm <commit-message>"
        return 1
    fi
    git add . && git commit -m "$1"
}

# Quick commit and push
gcp() {
    if [ -z "$1" ]; then
        echo "Usage: gcp <commit-message>"
        return 1
    fi
    git add . && git commit -m "$1" && git push
}

# Show branch tracking info
gtrack() {
    git for-each-ref --format='%(refname:short) <- %(upstream:short)' refs/heads
}

# Clean up merged branches (except main/master/develop)
gclean() {
    echo "Deleting local branches that have been merged into current branch..."
    git branch --merged | grep -v "\*\|main\|master\|develop" | xargs -n 1 git branch -d
}

# ============================================================================
# Functions - Utilities
# ============================================================================

# Create directory and cd into it
mkcd() {
    mkdir -p "$1" && cd "$1"
}

# Extract archives (any format)
extract() {
    if [ -f "$1" ]; then
        case "$1" in
            *.tar.bz2)  tar xjf "$1"     ;;
            *.tar.gz)   tar xzf "$1"     ;;
            *.bz2)      bunzip2 "$1"     ;;
            *.rar)      unrar x "$1"     ;;
            *.gz)       gunzip "$1"      ;;
            *.tar)      tar xf "$1"      ;;
            *.tbz2)     tar xjf "$1"     ;;
            *.tgz)      tar xzf "$1"     ;;
            *.zip)      unzip "$1"       ;;
            *.Z)        uncompress "$1"  ;;
            *.7z)       7z x "$1"        ;;
            *)          echo "'$1' cannot be extracted via extract()" ;;
        esac
    else
        echo "'$1' is not a valid file"
    fi
}

# Find file by name in current directory tree
ff() {
    find . -type f -iname "*$1*"
}

# Find directory by name in current directory tree
fd() {
    find . -type d -iname "*$1*"
}

# ============================================================================
# Terminal Efficiency Tools
# ============================================================================

# atuin - Magical shell history (replaces/enhances Ctrl+R)
# Syncs history across machines, contextual search, better than FZF history
if command -v atuin &> /dev/null; then
    eval "$(atuin init bash --disable-up-arrow)"
fi

# broot - Better directory navigation
# Use 'br' to launch interactive directory navigator
# Overrides the default br function to fix Windows path format (MINGW64/Git Bash)
if [ -f ~/.config/broot/launcher/bash/br ]; then
    source ~/.config/broot/launcher/bash/br
fi
function br {
    local cmd cmd_file code
    cmd_file=$(mktemp)
    if broot --outcmd "$cmd_file" "$@"; then
        cmd=$(<"$cmd_file")
        command rm -f "$cmd_file"
        # Translate Windows paths (C:\...) to bash paths (/c/...) for MINGW64
        if [[ "$cmd" == cd\ * ]]; then
            local dir="${cmd#cd }"
            dir="${dir//\"/}"
            dir=$(cygpath -u "$dir" 2>/dev/null || echo "$dir")
            cmd="cd \"$dir\""
        fi
        eval "$cmd"
    else
        code=$?
        command rm -f "$cmd_file"
        return "$code"
    fi
}

# direnv - Auto-load/unload environment per directory
# Create .envrc in project dirs with env vars, secrets, venv activation
if command -v direnv &> /dev/null; then
    eval "$(direnv hook bash)"
fi

# navi - Interactive cheatsheets
# Press Ctrl+G for interactive command search
if command -v navi &> /dev/null && [[ $- == *i* ]]; then
    eval "$(navi widget bash)"
fi

# ============================================================================
# FZF Configuration (Fuzzy Finder - THE GAME CHANGER!)
# ============================================================================

# Enable fzf key bindings and completion
# Ctrl+R - Search command history
# Ctrl+T - Search files
# Alt+C  - Change directory
eval "$(fzf --bash)"

# Use ripgrep with fzf (faster, respects .gitignore)
export FZF_DEFAULT_COMMAND='rg --files --hidden --follow --glob "!.git/*"'
export FZF_CTRL_T_COMMAND="$FZF_DEFAULT_COMMAND"

# Use bat for file preview in fzf
export FZF_CTRL_T_OPTS="
  --preview 'bat --color=always --line-range :500 {}'
  --bind shift-up:preview-page-up,shift-down:preview-page-down"

# Better colors (Dracula theme)
export FZF_DEFAULT_OPTS='
  --height 40%
  --border
  --layout=reverse
  --info=inline
  --color=fg:#f8f8f2,bg:#282a36,hl:#bd93f9
  --color=fg+:#f8f8f2,bg+:#44475a,hl+:#bd93f9
  --color=info:#ffb86c,prompt:#50fa7b,pointer:#ff79c6
  --color=marker:#ff79c6,spinner:#ffb86c,header:#6272a4'

# Custom fzf function: Search file contents with preview
fif() {
    if [ -z "$1" ]; then
        echo "Usage: fif <search-pattern>"
        return 1
    fi
    rg --files-with-matches --no-messages "$1" | \
    fzf --preview "bat --color=always {} | rg --colors 'match:bg:yellow' --ignore-case --pretty --context 10 '$1' || rg --ignore-case --pretty --context 10 '$1' {}"
}

# Custom fzf function: Interactive git branch checkout
fgb() {
    local branch
    branch=$(git branch -a | \
             grep -v HEAD | \
             sed 's/remotes\/origin\///' | \
             sort -u | \
             fzf --height 40% --reverse --info inline \
                 --preview 'git log --oneline --graph --date=short --pretty="format:%C(auto)%cd %h%d %s" $(sed "s/.* //" <<< {}) | head -200') && \
    git checkout $(echo "$branch" | sed 's/^[* ]*//')
}

# Custom fzf function: Interactive kill process
fkill() {
    local pid
    pid=$(ps -ef | sed 1d | fzf -m | awk '{print $2}')
    if [ -n "$pid" ]; then
        echo "$pid" | xargs kill -${1:-9}
    fi
}

# ============================================================================
# Additional Productivity Tools & Functions
# ============================================================================

# lazygit - Beautiful terminal UI for git
alias lg='lazygit'

# tldr - Simplified man pages
alias help='tldr'

# duf - Better df (disk usage)
alias df='duf'

# procs - Better ps (process viewer)
alias ps='procs'

# dust - Better du (directory sizes)
alias du='dust'

# glow - Markdown viewer in terminal
alias md='glow'

# jq - JSON processor
alias jqp='jq "."'                  # Pretty print JSON
alias jqk='jq "keys"'               # Show JSON keys

# yq - YAML processor
alias yqp='yq eval "." -P'          # Pretty print YAML

# curlie - Better curl (HTTPie alternative)
alias http='curlie'                 # HTTPie-style syntax

# shellcheck - Bash script linter
alias sc='shellcheck'

# Quick command to view markdown files beautifully
readme() {
    if [ -f "README.md" ]; then
        glow README.md
    else
        echo "No README.md found in current directory"
    fi
}

# Weather in terminal
weather() {
    curl -s "wttr.in/${1:-}" | head -37
}

# Cheat sheets (using cheat.sh)
cheat() {
    curl -s "cheat.sh/$1"
}

# Quick HTTP server
serve() {
    python -m http.server ${1:-8000}
}

# Show directory sizes sorted
dsize() {
    dust -d 1 -r "${1:-.}"
}

# Count lines of code in current directory
loc() {
    fd -e cs -e js -e ts -e py -e java | xargs wc -l | sort -n
}

# Git shortcuts with better UX
gaa() {
    git add .
    echo "✓ All changes staged"
    git status --short
}

# Quick git commit (with validation)
qc() {
    if [ -z "$1" ]; then
        echo "Usage: qc \"commit message\""
        return 1
    fi
    git add . && git commit -m "$1"
}

# Quick commit and push
qcp() {
    if [ -z "$1" ]; then
        echo "Usage: qcp \"commit message\""
        return 1
    fi
    git add . && git commit -m "$1" && git push
}

# Show file/directory tree with size
tre() {
    eza --tree --level=${1:-2} --long --icons --git
}

# Pretty print JSON file or stdin
jqf() {
    if [ -z "$1" ]; then
        jq "." -C | less -R
    else
        jq "." -C "$1" | less -R
    fi
}

# Extract specific JSON field
jqx() {
    if [ -z "$1" ]; then
        echo "Usage: jqx <field> [file]"
        echo "Example: jqx '.name' package.json"
        return 1
    fi
    if [ -z "$2" ]; then
        jq "$1"
    else
        jq "$1" "$2"
    fi
}

# Pretty print YAML file or stdin
yqf() {
    if [ -z "$1" ]; then
        yq eval "." -P -C | less -R
    else
        yq eval "." -P -C "$1" | less -R
    fi
}

# Convert JSON to YAML
j2y() {
    if [ -z "$1" ]; then
        yq eval -P
    else
        yq eval -P "$1"
    fi
}

# Convert YAML to JSON
y2j() {
    if [ -z "$1" ]; then
        yq eval -o=json
    else
        yq eval -o=json "$1"
    fi
}

# Quick HTTP GET with pretty output
get() {
    curlie GET "$@"
}

# Quick HTTP POST with JSON
post() {
    if [ -z "$1" ]; then
        echo "Usage: post <url> [json-data]"
        echo "Example: post https://api.example.com/users name=John age=30"
        return 1
    fi
    curlie POST "$@"
}

# Lint bash script
lint() {
    if [ -z "$1" ]; then
        echo "Usage: lint <script.sh>"
        return 1
    fi
    shellcheck -x "$1"
}

# GitHub CLI shortcuts
ghpr() {
    gh pr view --web
}

ghissue() {
    gh issue view --web
}

ghrepo() {
    gh repo view --web
}

# ============================================================================
# Docker Functions
# ============================================================================

# Enter running container shell
dsh() {
    if [ -z "$1" ]; then
        echo "Usage: dsh <container-name-or-id>"
        return 1
    fi
    docker exec -it "$1" bash || docker exec -it "$1" sh
}

# View container logs with tail
dlog() {
    if [ -z "$1" ]; then
        echo "Usage: dlog <container-name-or-id> [lines]"
        return 1
    fi
    docker logs -f --tail ${2:-100} "$1"
}

# Inspect container details
dins() {
    if [ -z "$1" ]; then
        echo "Usage: dins <container-name-or-id>"
        return 1
    fi
    docker inspect "$1" | jq "."
}

# Show container resource usage
dstats() {
    docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"
}

# Remove stopped containers
drmall() {
    local stopped=$(docker ps -aq -f status=exited)
    if [ -n "$stopped" ]; then
        docker rm -v $stopped
        echo "✓ Removed all stopped containers"
    else
        echo "No stopped containers to remove"
    fi
}

# Remove dangling images
drmiall() {
    local dangling=$(docker images -qf "dangling=true")
    if [ -n "$dangling" ]; then
        docker rmi $dangling
        echo "✓ Removed all dangling images"
    else
        echo "No dangling images to remove"
    fi
}

# Full Docker cleanup
dfullclean() {
    echo "🧹 Cleaning Docker..."
    drmall
    drmiall
    docker volume prune -f
    docker network prune -f
    docker system prune -f
    echo "✓ Docker cleanup complete"
}

# Analyze Docker image layers
dimglayers() {
    if [ -z "$1" ]; then
        echo "Usage: dimglayers <image-name>"
        return 1
    fi
    dive "$1"
}

# Quick docker compose for current directory
dup() {
    docker compose up -d "$@" && docker compose logs -f
}

ddown() {
    docker compose down "$@"
}

# Restart specific service in compose
dcr() {
    if [ -z "$1" ]; then
        echo "Usage: dcr <service-name>"
        return 1
    fi
    docker compose restart "$1" && docker compose logs -f "$1"
}

# ============================================================================
# Smart CD with auto-ls
# ============================================================================

# Automatically ls after cd
cd() {
    builtin cd "$@" && ll
}

# ============================================================================
# Welcome Message
# ============================================================================

# Show git status if in a git repository
if git rev-parse --git-dir > /dev/null 2>&1; then
    echo "Git repository detected. Use 'gs' for status."
fi

# ============================================================================
# Machine-specific overrides (not in git — create ~/.bashrc.local per machine)
# ============================================================================
[ -f ~/.bashrc.local ] && source ~/.bashrc.local
