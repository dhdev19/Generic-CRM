function onFormSubmit(e) {
  try {
    var sheet = e.source.getSheetByName(e.range.getSheet().getName());
    var row = e.range.getRow();

    // Read values from current row
    var name = sheet.getRange(row, 2).getValue();     // B: Name
    var phone = sheet.getRange(row, 3).getValue();    // C: Phone
    var mail = sheet.getRange(row, 4).getValue();     // D: Email
    var service = sheet.getRange(row, 5).getValue();  // E: Service
    var source = sheet.getRange(row, 6).getValue();   // F: Source
    var statusCell = sheet.getRange(row, 7);          // G: Status

    var currentStatus = statusCell.getValue();

    // ❌ Skip only if ADDED already
    if (currentStatus === "ADDED") {
      Logger.log("Skipping row " + row + " — already ADDED");
      return;
    }

    // Handle empty email - default to johndoe@example.com
    if (mail == "" || !mail) {
      mail = "johndoe@example.com";
    }

    // Build payload with source included
    var payload = {
      name: name,
      phone_number: phone,
      mail_id: mail,
      service_query: service,
      source: source  // ✅ Include source in payload
    };

    var apiUrl = "https://crm.digitalhomeez.in/api/formAdd";
    var options = {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    var response = UrlFetchApp.fetch(apiUrl, options);
    var status = response.getResponseCode();
    var responseText = response.getContentText();

    // ✔ Success
    if (status === 200 || status === 201) {
      statusCell.setValue("ADDED");
      Logger.log("Success Row " + row + " → ADDED");
    } 
    // ❌ Error - log properly
    else {
      // Parse response if possible
      var errorMessage = "";
      try {
        var responseJson = JSON.parse(responseText);
        errorMessage = responseJson.message || responseText;
      } catch (e) {
        errorMessage = responseText || "Unknown error";
      }
      
      // Set status with proper error message
      statusCell.setValue("FAILED [" + status + "] " + errorMessage);
      Logger.log("Failed Row: " + row + " → Status: " + status);
      Logger.log("Payload: " + JSON.stringify(payload));
      Logger.log("Response: " + responseText);
    }

  } catch (error) {
    Logger.log("Error: " + error);
    Logger.log("Stack: " + error.stack);
    sheet.getRange(row, 7).setValue("FAILED [" + error.toString() + "]");
  }
}
