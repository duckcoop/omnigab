# New Workstation Setup Procedure

## Hardware Standards

All new workstations must meet the following minimum specifications: Intel Core i5 (12th gen or newer) or AMD Ryzen 5 (5000 series or newer) processor, 16 GB DDR4 RAM minimum, 512 GB NVMe SSD, integrated or discrete graphics (discrete GPU required for engineering and design teams), dual monitor support. Our standard models are the Dell OptiPlex 7020 (desktop) and Dell Latitude 5550 (laptop).

## Operating System Deployment

### Imaging Process

1. Connect the new workstation to the network via Ethernet cable in the IT staging area.
2. Boot the workstation and press F12 to enter the boot menu.
3. Select "PXE Network Boot" to boot from the network.
4. The workstation will connect to our SCCM (System Center Configuration Manager) deployment server at 10.0.5.50.
5. Select the appropriate task sequence based on the user's department: "Standard Desktop - Corporate", "Engineering Workstation", or "Design Workstation."
6. The imaging process takes approximately 45 to 60 minutes and includes Windows 11 Enterprise, Microsoft 365 Apps, Cisco AnyConnect VPN, CrowdStrike Falcon endpoint protection, and department-specific applications.
7. After imaging, the workstation will automatically restart and join the company domain.

### Post-Imaging Configuration

After the imaging process completes, perform these steps:

1. Log in with the IT admin account (credentials in the IT password vault).
2. Verify the workstation has joined the domain by checking System Properties.
3. Run Windows Update to install any patches released since the image was created.
4. Open SCCM Software Center and verify all assigned applications are installed.
5. Configure the user's email profile in Outlook by entering their email address and allowing Autodiscover to complete the setup.
6. Map network drives: H: drive to the user's home folder (\\fileserver\users\username), S: drive to the shared department folder (\\fileserver\departments\[dept]), and P: drive to the projects folder (\\fileserver\projects).
7. Install any additional software requested on the setup ticket.
8. Set the default printer for the user's floor or office area.

## Printer Setup

Network printers are deployed via Group Policy based on the user's OU location. If a printer does not appear automatically, add it manually through Settings, then Printers and Scanners, then Add Printer. Use the TCP/IP address from the printer inventory spreadsheet on SharePoint. Driver packages are available on the print server at \\printserver\drivers.

## Peripheral Configuration

### Docking Station

Our standard docking station is the Dell WD22TB4 Thunderbolt dock. Drivers install automatically through Windows Update. If the dock is not recognized, install the Dell Command Update utility from Software Center and run a driver scan. Connect monitors to the dock's DisplayPort or HDMI outputs. USB peripherals including keyboard, mouse, and headset should be connected to the dock rather than directly to the laptop.

### Multi-Monitor Setup

For dual monitor configuration, right-click on the desktop and select Display Settings. Arrange the monitors to match their physical layout. Set the primary display (usually the left monitor). Recommended resolution is 1920x1080 or higher. For the engineering team, 4K monitors are standard and should be set to 3840x2160 at 100% scaling.

## Security Baseline

Every workstation must have the following security measures in place before being deployed to the user: BitLocker drive encryption enabled on the OS drive (encryption key backed up to Active Directory), CrowdStrike Falcon sensor installed and reporting to the management console, Windows Firewall enabled with the domain profile active, local administrator account disabled (IT staff use a separate admin account for elevated tasks), USB storage device access restricted via Group Policy (exceptions require manager approval and IT security review).

## Troubleshooting New Workstation Issues

### Workstation Not Joining Domain

If the workstation fails to join the domain during imaging, verify the Ethernet cable is connected and the workstation has received a DHCP address. Check that the computer account does not already exist in AD (may need to be deleted or reset). Verify DNS settings point to our domain controllers (10.0.1.10 and 10.0.1.11). Try manually joining the domain through System Properties by entering company.local as the domain name.

### Applications Not Installing from SCCM

If Software Center shows applications as "Available" but they do not install, restart the SCCM agent service (CcmExec). Check the SCCM client logs at C:\Windows\CCM\Logs for error details. Verify the workstation is in the correct AD OU and SCCM collection. If the issue persists, remove and reinstall the SCCM client using the command: ccmsetup.exe /uninstall followed by ccmsetup.exe SMSSITECODE=ABC.
