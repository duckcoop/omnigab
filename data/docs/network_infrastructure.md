# Network Infrastructure Documentation

## Network Architecture

Our corporate network uses a three-tier architecture consisting of core, distribution, and access layers. The core layer uses two Cisco Catalyst 9500 switches in a high-availability pair. The distribution layer consists of Cisco Catalyst 9300 switches, one per floor. The access layer uses Cisco Catalyst 9200 switches providing PoE+ to endpoints and wireless access points.

## IP Addressing Scheme

The internal network uses RFC 1918 private addressing. The primary subnet is 10.0.0.0/8, broken down as follows: 10.0.1.0/24 is the server VLAN (VLAN 10) hosting domain controllers, file servers, and application servers. 10.0.2.0/24 is the management VLAN (VLAN 20) for network device management. 10.0.10.0/24 through 10.0.50.0/24 are user VLANs organized by floor. 10.0.100.0/24 is the DMZ for public-facing servers. 10.0.200.0/24 is the guest Wi-Fi network, which is completely isolated from the corporate network.

## DHCP Configuration

DHCP services run on our two Windows Server 2022 domain controllers (10.0.1.10 and 10.0.1.11) in a failover configuration. DHCP scopes are configured for each user VLAN with a lease duration of 8 hours. Reservations are used for printers and other static devices. The DHCP servers also push DNS server addresses (10.0.1.10 and 10.0.1.11) and the default gateway for each VLAN to clients.

## DNS Configuration

Internal DNS zones are hosted on the domain controllers and replicated through Active Directory-integrated DNS. The primary zone is company.local for internal resources. Conditional forwarders are configured for partner domains. External DNS resolution uses Cloudflare DNS (1.1.1.1 and 1.0.0.1) as upstream forwarders. DNS logging is enabled and logs are sent to the SIEM for security monitoring.

## Wireless Network

The corporate wireless network uses Cisco 9800 wireless controllers with Catalyst 9166 access points. Three SSIDs are broadcast: "Corporate" (802.1X authentication using AD credentials, WPA3-Enterprise), "Corporate-Guest" (captive portal with sponsor approval, isolated on VLAN 200), and "IoT-Devices" (WPA2-PSK, isolated on its own VLAN for printers, displays, and conference room equipment).

## Firewall Rules

The perimeter firewall is a Palo Alto PA-5400 in active/passive HA. Key rules include allowing outbound HTTP/HTTPS for all user VLANs, allowing inbound HTTPS to the DMZ web servers only, blocking all inbound connections to user VLANs, allowing VPN traffic (UDP 443 and TCP 443) to the VPN concentrator, and permitting inter-VLAN routing only for approved traffic flows. All traffic is inspected by the firewall's threat prevention engine. URL filtering blocks categories including malware, phishing, adult content, and gambling.

## Monitoring

Network monitoring uses a combination of tools. Nagios Core monitors device availability with 1-minute polling intervals. PRTG monitors bandwidth utilization on all switch uplinks and WAN connections. Cisco DNA Center provides wireless analytics and client troubleshooting. All network device logs are forwarded to the Splunk SIEM at siem.company.local for correlation and alerting. Critical alerts are sent to the NOC team via PagerDuty.
