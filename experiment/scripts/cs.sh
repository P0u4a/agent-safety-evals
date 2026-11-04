#!/bin/bash
exec ssh -i ~/.ssh/colab_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ServerAliveInterval=30 -o "ProxyCommand=colab ssh --proxy-mode -s em -i $HOME/.ssh/colab_ed25519" root@colab-em "$@"
