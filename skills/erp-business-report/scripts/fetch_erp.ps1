param(
    [Parameter(Mandatory=$true)][string]$Config,
    [string]$StartDate,
    [string]$EndDate
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Net.Http
$client = $null
try {
    $cfg = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
    $uri = [Uri]$cfg.base_url
    if ($uri.Scheme -ne 'http' -or $uri.Host -notin @('localhost','127.0.0.1') -or $uri.Port -ne 8080) { throw 'CONFIG_INVALID' }
    if (($StartDate -and -not $EndDate) -or ($EndDate -and -not $StartDate)) { throw 'DATE_INVALID' }
    if ($StartDate) {
        $start = [datetime]::ParseExact($StartDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
        $end = [datetime]::ParseExact($EndDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
        if ($start -gt $end) { throw 'DATE_INVALID' }
    }
    # Public adapter: inject credentials from a trusted local process environment.
    # Never store real values in source, runtime.json, logs, or Git.
    $apiKey = [Environment]::GetEnvironmentVariable('ERPNEXT_API_KEY')
    $apiSecret = [Environment]::GetEnvironmentVariable('ERPNEXT_API_SECRET')
    if (-not $apiKey -or -not $apiSecret) { throw 'CREDENTIAL_IDENTITY_MISMATCH' }
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(25)
    $client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('token', ($apiKey + ':' + $apiSecret))
    $apiKey = $null
    $apiSecret = $null
    function Get-SafeJson([string]$Path) {
        try {
            $response = $client.GetAsync(($cfg.base_url.TrimEnd('/') + $Path)).GetAwaiter().GetResult()
            $code = [int]$response.StatusCode
            if (-not $response.IsSuccessStatusCode) { $response.Dispose(); return @{ ok=$false; code=('HTTP_' + $code); http_status=$code } }
            $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            $response.Dispose()
            try { $parsed = $body | ConvertFrom-Json } catch { return @{ ok=$false; code='INVALID_JSON' } }
            return @{ ok=$true; value=$parsed }
        } catch { return @{ ok=$false; code='NETWORK_OR_TIMEOUT' } }
    }
    $identity = Get-SafeJson '/api/method/frappe.auth.get_logged_user'
    if (-not $identity.ok -or $identity.value.message -ne $cfg.api_user) { throw 'API_IDENTITY_NOT_VERIFIED' }
    function Get-Resource([string]$DocType, [string[]]$Fields, [object[]]$Filters) {
        $rows = New-Object 'System.Collections.Generic.List[object]'
        $seen = New-Object 'System.Collections.Generic.HashSet[string]'
        $offset = 0
        $pages = 0
        $issue = $null
        $complete = $false
        $limit = [int]$cfg.page_size
        if ($limit -lt 1 -or $limit -gt 1000 -or [int]$cfg.max_pages -lt 1) { throw 'CONFIG_INVALID' }
        while ($pages -lt [int]$cfg.max_pages) {
            $query = 'fields=' + [Uri]::EscapeDataString((ConvertTo-Json -InputObject $Fields -Compress))
            $query += '&filters=' + [Uri]::EscapeDataString((ConvertTo-Json -InputObject $Filters -Depth 8 -Compress))
            $query += '&order_by=' + [Uri]::EscapeDataString('name asc') + '&limit_page_length=' + $limit + '&limit_start=' + $offset
            $result = Get-SafeJson ('/api/resource/' + [Uri]::EscapeDataString($DocType) + '?' + $query)
            $pages++
            if (-not $result.ok) { $issue = $result.code; break }
            if (-not ($result.value.data -is [Array])) { $issue = 'INVALID_DATA_SHAPE'; break }
            $page = @($result.value.data)
            if ($page.Count -eq 0) { $complete = $true; break }
            foreach ($row in $page) {
                if (-not $row.name -or -not $seen.Add([string]$row.name)) { $issue = 'REPEATED_OR_UNNAMED_ROW'; break }
                # Whitelist fields: never emit unrelated personal data or credentials.
                $safe = [ordered]@{}
                foreach ($field in $Fields) { if ($row.PSObject.Properties.Name -contains $field) { $safe[$field] = $row.$field } }
                $rows.Add($safe)
            }
            if ($issue) { break }
            # Advance by actual results; an ERP server may cap the requested page size.
            $offset += $page.Count
        }
        if (-not $complete -and -not $issue) { $issue = 'PAGE_LIMIT_REACHED' }
        return @{rows=@($rows.ToArray()); complete=$complete; error=$issue; pages=$pages}
    }
    $began = [DateTimeOffset]::UtcNow.ToString('o')
    $soFilters = ,@('company','=',[string]$cfg.company)
    if ($StartDate) { $soFilters += ,@('transaction_date','between',@($StartDate,$EndDate)) }
    $data = [ordered]@{
        source='ERPNext'; timezone=$cfg.timezone; company=$cfg.company; query_started_at=$began;
        Item=(Get-Resource 'Item' @('name','item_code','item_name','stock_uom','is_stock_item','disabled') @(@('is_stock_item','=',1),@('disabled','=',0)));
        'Sales Order'=(Get-Resource 'Sales Order' @('name','transaction_date','grand_total','currency','status','docstatus','per_delivered','per_billed') $soFilters);
        Bin=(Get-Resource 'Bin' @('name','item_code','warehouse','company','actual_qty','reserved_qty') (,@('company','=',[string]$cfg.company)));
        queried_at=[DateTimeOffset]::UtcNow.ToString('o'); identity_verified=$true
    }
    ConvertTo-Json -InputObject $data -Depth 16 -Compress
} catch {
    # Never print exception bodies, HTTP response bodies, paths to credentials, or tokens.
    $safeCodes = @('CONFIG_INVALID','DATE_INVALID','CREDENTIAL_IDENTITY_MISMATCH','API_IDENTITY_NOT_VERIFIED')
    $safeReason = 'LOCAL_CREDENTIAL_OR_SCRIPT_ERROR'
    if ($_.Exception.Message -in $safeCodes) { $safeReason = $_.Exception.Message }
    ConvertTo-Json -InputObject @{fatal='READ_ONLY_CONNECTION_UNAVAILABLE'; reason=$safeReason; exception_type=$_.Exception.GetType().Name; hint='Configure authorized read-only process credentials; do not use ERP Administrator.'} -Compress
    exit 2
} finally {
    if ($client) { $client.Dispose() }
}
