# ~/.bashrc - Bash configuration (sourced by .bash_profile)

# ============================================================================
# SSH Agent Configuration
# ============================================================================
# Automatically start SSH agent and load keys to avoid repeated password prompts

env=~/.ssh/agent.env

agent_load_env() { test -f "$env" && . "$env" >| /dev/null; }

agent_start() {
    (umask 077; ssh-agent >| "$env")
    . "$env" >| /dev/null
}

agent_load_env

# agent_run_state: 0=agent running w/ key; 1=agent w/o key; 2=agent not running
agent_run_state=$(ssh-add -l >| /dev/null 2>&1; echo $?)

if [ ! "$SSH_AUTH_SOCK" ] || [ $agent_run_state = 2 ]; then
    agent_start
    ssh-add
elif [ "$SSH_AUTH_SOCK" ] && [ $agent_run_state = 1 ]; then
    ssh-add
fi

unset env

# ============================================================================
# Shell Options
# ============================================================================

# Append to history file, don't overwrite it
shopt -s histappend

# Check window size after each command
shopt -s checkwinsize

# Autocorrect minor errors in cd commands
shopt -s cdspell

# Enable extended pattern matching
shopt -s extglob

# Enable recursive globbing with **
shopt -s globstar 2>/dev/null

# ============================================================================
# History Configuration
# ============================================================================

export HISTSIZE=10000000
export HISTFILESIZE=10000000
export HISTCONTROL=ignoreboth:erasedups  # Ignore duplicates and commands starting with space
export HISTTIMEFORMAT="%F %T "            # Add timestamps to history

# ============================================================================
# Environment Variables
# ============================================================================

# Make less more friendly for non-text input files
[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"

# Set default editor
export EDITOR=vim
export VISUAL=vim

# Better ls colors for Git Bash
export LS_COLORS='di=1;34:fi=0:ln=1;36:pi=5:so=5:bd=5:cd=5:or=31:mi=0:ex=1;32'

# ============================================================================
# PATH Additions
# ============================================================================

export PATH="$HOME/tools/acli/bin:$PATH"
export PATH="$HOME/ACLI/bin:$PATH"

# ============================================================================
# Completion
# ============================================================================

# Enable programmable completion features
if [ -f /etc/bash_completion ] && ! shopt -oq posix; then
    . /etc/bash_completion
fi

# Git completion for custom functions (defined in .bash_profile)
if declare -f __git_complete >/dev/null 2>&1; then
    __git_complete gc _git_checkout
    __git_complete gcb _git_checkout
fi
