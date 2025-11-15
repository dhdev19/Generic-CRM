<?php
if (isset($_POST['query'])){

   // Honeypot Spam Protection
    if (!empty($_POST['company_name'])) {
        $log = "Spam blocked on: " . date("Y-m-d H:i:s") . " | Value: " . $_POST['company_name'] . "\n";
        file_put_contents("spam_log.txt", $log, FILE_APPEND);
        die("Spam detected. Submission blocked.");
    }
	
    $name = $_POST['name'];
    $number = $_POST['number']; 
    $service = $_POST['service'];
    // Get email if available, otherwise use default
    $email = isset($_POST['email']) ? $_POST['email'] : 'johndoe@example.com';

    $mail = new PHPMailer(true);

    try {
        //Server settings
        // $mail->SMTPDebug = SMTP::DEBUG_SERVER;                      //Enable verbose debug output
        $mail->isSMTP();                                            //Send using SMTP
        $mail->Host       = 'digitalhomeez.in';                     //Set the SMTP server to send through
        $mail->SMTPAuth   = true;                                   //Enable SMTP authentication
        $mail->Username   = 'official@digitalhomeez.in';            //SMTP username
        $mail->Password   = 'Office@Dh25';                          //SMTP password
        $mail->SMTPSecure = PHPMailer::ENCRYPTION_SMTPS;            //Enable implicit TLS encryption
        $mail->Port       = 465;                                    //TCP port to connect to; use 587 if you have set SMTPSecure = PHPMailer::ENCRYPTION_STARTTLS

        //Recipients
        $mail->setFrom('official@digitalhomeez.in', 'Digital Homeez  | Query');
        $mail->addAddress('official@digitalhomeez.in', 'Digital Homeez  | Query');     //Add a recipient

        //Content
        $mail->isHTML(true);                                  //Set email format to HTML
        $mail->Subject = 'Services | Enquiry Form';
        $mail->Body    = "Name: $name <br>   Phone: $number <br> Service: $service ";

        $mail->send();
        
        // Call CRM API to save lead
        $api_url = 'https://crm.digitalhomeez.in/api/website/lead'; // Replace with your actual domain
        $api_data = [
            'name' => $name,
            'phone_number' => $number,
            'service_query' => $service,
            'mail_id' => $email
        ];
        
        $ch = curl_init($api_url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($api_data));
        curl_setopt($ch, CURLOPT_HTTPHEADER, [
            'Content-Type: application/json'
        ]);
        
        $api_response = curl_exec($ch);
        $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        
        // Optional: Log API response for debugging
        if ($http_code !== 200) {
            $log = "API call failed on: " . date("Y-m-d H:i:s") . " | HTTP Code: $http_code | Response: $api_response\n";
            file_put_contents("api_log.txt", $log, FILE_APPEND);
        }
        
        header("Location: thank-you.php");
    } catch (Exception $e) {
        echo "Message could not be sent. Mailer Error: {$mail->ErrorInfo}";
    }
}

if (isset($_POST['contquery'])){
    $name = $_POST['name'];
    $phone = $_POST['phone'];
    $email = $_POST['email'];
    $subject = $_POST['subject'];
    $message = $_POST['message'];
    
    $mail = new PHPMailer(true);

    try {
        //Server settings
        // $mail->SMTPDebug = SMTP::DEBUG_SERVER;                      //Enable verbose debug output
        $mail->isSMTP();                                            //Send using SMTP
        $mail->Host       = 'digitalhomeez.in';                     //Set the SMTP server to send through
        $mail->SMTPAuth   = true;                                   //Enable SMTP authentication
        $mail->Username   = 'official@digitalhomeez.in';            //SMTP username
        $mail->Password   = 'Office@Dh25';                          //SMTP password
        $mail->SMTPSecure = PHPMailer::ENCRYPTION_SMTPS;            //Enable implicit TLS encryption
        $mail->Port       = 465;                                    //TCP port to connect to; use 587 if you have set SMTPSecure = PHPMailer::ENCRYPTION_STARTTLS

        //Recipients
        $mail->setFrom('official@digitalhomeez.in', 'Digital Homeez');
        $mail->addAddress('official@digitalhomeez.in', 'Digital Homeez');     //Add a recipient
        
        //Content
        $mail->isHTML(true);                                  //Set email format to HTML
        $mail->Subject = 'Contact us | Enquiry Form';
        $mail->Body    = "Name: $name <br> Email: $email <br> Phone: $phone  <br> Subject: $subject <br> Message: $message";
       
        $mail->send();
        
        // Call CRM API to save lead
        $api_url = 'https://crm.digitalhomeez.in/api/website/lead';
        // Combine subject and message for service_query
        $service_query = $subject . ": " . $message;
        $api_data = [
            'name' => $name,
            'phone_number' => $phone,
            'service_query' => $service_query,
            'mail_id' => $email
        ];
        
        $ch = curl_init($api_url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($api_data));
        curl_setopt($ch, CURLOPT_HTTPHEADER, [
            'Content-Type: application/json'
        ]);
        
        $api_response = curl_exec($ch);
        $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        
        // Optional: Log API response for debugging
        if ($http_code !== 200) {
            $log = "API call failed on: " . date("Y-m-d H:i:s") . " | HTTP Code: $http_code | Response: $api_response\n";
            file_put_contents("api_log.txt", $log, FILE_APPEND);
        }
        
        header("Location: thank-you.php");
    } catch (Exception $e) {
        echo "Message could not be sent. Mailer Error: {$mail->ErrorInfo}";
    }
}
?>

