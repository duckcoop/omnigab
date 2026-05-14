# VPN Configuration and Troubleshooting Guide

## Overview

Our organization uses Cisco AnyConnect Secure Mobility Client version 5.1 for remote access VPN. All remote employees must connect through the VPN to access internal resources including file shares, intranet applications, and the Active Directory domain.

## Initial VPN Setup

### Installation

1. Download the Cisco AnyConnect client from the IT self-service portal at https://itportal.company.com/software.
2. Run the installer with administrator privileges.
3. During installation, select only the "VPN" module. The Posture and Web Security modules are not required.
4. Restart the computer after installation completes.

### First-Time Connection

1. Launch Cisco AnyConnect from the Start menu.
2. Enter the VPN gateway address: vpn.company.com
3. Click Connect.
4. When prompted, enter your Active Directory credentials (same username and password you use to log into your workstation).
5. You will receive a push notification on your phone from the Microsoft Authenticator app. Approve the notification to complete the multi-factor authentication.
6. Once connected, the AnyConnect icon in the system tray will show a lock symbol.

## Split Tunnel Configuration

Our VPN uses split tunneling, which means only traffic destined for company resources goes through the VPN tunnel. Internet traffic goes directly through the user's local internet connection. The following subnets are routed through the VPN tunnel: 10.0.0.0/8 (internal network), 172.16.0.0/12 (server VLAN), and 192.168.100.0/24 (management network).

## Troubleshooting Common Issues

### Connection Timeout

If the VPN connection times out, check the following: verify your internet connection is working by browsing to an external website. Check that the VPN gateway address is correct (vpn.company.com). Try disconnecting and reconnecting. If using Wi-Fi, try switching to a wired connection. Some public Wi-Fi networks block VPN protocols. Try using the AnyConnect "Allow local LAN access" option in Preferences.

### Authentication Failures

If you receive an authentication error: verify your Active Directory password has not expired. Check that your account is not locked out. Ensure the Microsoft Authenticator app is configured correctly. If you recently changed your password, try the new password. Contact the helpdesk if the issue persists after verifying all of the above.

### Slow VPN Performance

VPN performance depends on your local internet connection quality. Minimum recommended bandwidth is 10 Mbps download and 5 Mbps upload. For video conferencing over VPN, 25 Mbps download is recommended. If performance is slow, check your internet speed at speedtest.net. Close bandwidth-heavy applications. Consider using the web versions of applications when possible, as they may perform better over VPN.

### DNS Resolution Issues

If you cannot resolve internal hostnames while connected to VPN: open a command prompt and run `ipconfig /flushdns`. Then run `nslookup intranet.company.com` to test DNS resolution. The VPN should configure DNS servers automatically (10.0.1.10 and 10.0.1.11). If DNS is not working, disconnect and reconnect the VPN. As a workaround, you can manually add DNS entries in your hosts file at C:\Windows\System32\drivers\etc\hosts.
