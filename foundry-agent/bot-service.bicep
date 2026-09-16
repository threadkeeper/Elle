param botName string = 'bot-elle'
param displayName string = 'Elle'
param msaAppId string
param tenantId string
param endpoint string

resource botService 'Microsoft.BotService/botServices@2022-09-15' = {
  name: botName
  kind: 'azurebot'
  location: 'global'
  sku: {
    name: 'F0'
  }
  properties: {
    displayName: displayName
    endpoint: endpoint
    msaAppId: msaAppId
    msaAppTenantId: tenantId
    msaAppType: 'SingleTenant'
    publicNetworkAccess: 'Disabled'
  }
}

resource teamsChannel 'Microsoft.BotService/botServices/channels@2021-03-01' = {
  parent: botService
  location: 'global'
  name: 'MsTeamsChannel'
  properties: {
    channelName: 'MsTeamsChannel'
  }
}

output botServiceArmId string = botService.id
