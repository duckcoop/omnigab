# Active Directory Administration Guide

## Password Reset Procedures

When a user is locked out or has forgotten their password, follow these steps to reset it in Active Directory.

### Standard Password Reset

1. Open Active Directory Users and Computers (ADUC) from the Start menu or by running `dsa.msc`.
2. Navigate to the Organizational Unit (OU) where the user account is located. Most user accounts are in the "Corporate Users" OU.
3. Right-click on the user account and select "Reset Password" from the context menu.
4. In the Reset Password dialog box, enter the new temporary password in both fields.
5. Check the box labeled "User must change password at next logon" to force the user to create their own password.
6. Click OK to apply the change.
7. If the account was locked out, also right-click the account, go to Properties, then the Account tab, and uncheck "Account is locked out."

### Self-Service Password Reset (SSPR)

Our organization uses Microsoft Entra ID Self-Service Password Reset. Users can reset their own passwords at https://passwordreset.microsoftonline.com by verifying their identity through their registered phone number or authenticator app. SSPR must be enabled by IT before users can enroll.

### Password Policy

Our domain enforces the following password requirements: minimum 14 characters, must include uppercase, lowercase, numbers, and special characters. Passwords expire every 90 days. The last 12 passwords are remembered and cannot be reused. Account lockout occurs after 5 failed login attempts within a 30-minute window. Lockout duration is 30 minutes, after which the account automatically unlocks.

## User Account Provisioning

### Creating a New User Account

1. Open Active Directory Users and Computers.
2. Navigate to the appropriate OU based on the user's department.
3. Right-click on the OU, select New, then User.
4. Fill in First Name, Last Name, and User Logon Name (format: first.last@company.com).
5. Set an initial password and check "User must change password at next logon."
6. Add the user to the appropriate security groups based on their role. Standard groups include: Domain Users, VPN Users, and the department-specific group.
7. Create a home folder at \\fileserver\users\username and set NTFS permissions.
8. Assign a Microsoft 365 license through the admin portal.

### Disabling an Account (Offboarding)

When an employee leaves the organization, their account must be disabled within 24 hours of their departure. Do not delete accounts immediately, as they may be needed for audit purposes. Move the disabled account to the "Disabled Users" OU. Remove all group memberships except Domain Users. Forward their email to their manager for 30 days. After 90 days, the account can be permanently deleted.

## Group Policy Overview

Group Policy Objects (GPOs) are applied in the following order: Local, Site, Domain, OU (LSDOU). Our key GPOs include the Desktop Lockdown Policy (applied to all workstations), the Software Deployment Policy (applied per department), and the Security Baseline Policy (applied domain-wide). To troubleshoot GPO issues, run `gpresult /r` on the affected workstation to see which policies are being applied.
