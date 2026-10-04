#!/bin/bash
#loading functions to script
export SECONDS=0
source .devcontainer/util/source_framework.sh

# All three vars are optional: the Bindplane logs lab is self-contained and does not need them.
# The Kubernetes operator + sample app deploys further down are gated on them being present.
variablesNeeded DT_ENVIRONMENT:false DT_OPERATOR_TOKEN:false DT_INGEST_TOKEN:false

setUpTerminal

startK3dCluster 

installK9s

#TODO: BeforeGoLive: uncomment this. This is only needed for professors to have the Mkdocs live in the container

#installMkdocs


# Deploy the Dynatrace operator and sample apps only when the Kubernetes-side secrets
# are present. The Bindplane logs lab does not need any of this and runs fine without it.
if [ -n "$DT_ENVIRONMENT" ] && [ -n "$DT_OPERATOR_TOKEN" ]; then
  # Dynatrace Operator can be deployed automatically
  dynatraceDeployOperator

  # You can deploy CNFS or AppOnly
  #deployCloudNative
  deployApplicationMonitoring

  # In here you deploy the Application you want
  # The TODO App will be deployed as a sample
  # deployTodoApp

  # The Astroshop keeping changes of demo.live needs certmanagerdocker
  #certmanagerInstall
  #certmanagerEnable
  #deployAstroshop
  deployApp astroshop
else
  printWarn "Skipping Dynatrace operator and sample app deploys - DT_ENVIRONMENT / DT_OPERATOR_TOKEN not set."
  printInfo "The Bindplane logs lab works without them. Set the two secrets and rebuild to enable the full environment."
fi

# If you want to deploy your own App, just create a function in the functions.sh file and call it here.
# deployMyCustomApp


#### Bindplane Stuff

# The generator writes to the real Linux log paths, so the lab looks like a
# production host rather than a sandbox directory. Pre-create the files it
# appends to and hand those to $USER; /var/log itself stays root-owned, as it
# is on a real host.
sudo mkdir -p /var/log/audit
sudo chown "$(id -un)":"$(id -gn)" /var/log/audit
for logfile in syslog auth.log kern.log cron.log fail2ban.log audit/audit.log; do
	sudo touch "/var/log/$logfile"
	sudo chown "$(id -un)":"$(id -gn)" "/var/log/$logfile"
done

if ! declare -F startLogGenerator > /dev/null; then
	printError "startLogGenerator is not defined. Ensure .devcontainer/util/my_functions.sh is sourced via source_framework.sh."
	exit 1
fi

# If the Codespace was created via Workflow end2end test will be done, otherwise
# it'll verify if there are error in the logs and will show them in the greeting as well a monitoring 
# notification will be sent on the instantiation details
finalizePostCreation

printInfoSection "Your dev container finished creating"
