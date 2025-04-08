$(function () {

    function clear_roles() {
        $("#div_id_highschool_admin_role, #div_id_district_admin_role").hide()
        
        toggle_role($('#id_role_type'))
    }

    function toggle_role(element) {
        if($(element).val() == 'highschool_admin') {
            $("#div_id_highschool_admin_role").show()
            $("#div_id_district_admin_role").hide()
        } else if($(element).val() == 'district_admin') {
            $("#div_id_district_admin_role").show()
            $("#div_id_highschool_admin_role").hide()
        } else if($(element).val() == 'college_admin') {
            $("#div_id_highschool_admin_role").hide()
            $("#div_id_district_admin_role").hide()
        }
    }
  
    $(document).on('change', '#id_role_type', function () {
      toggle_role(this)
    })
  
    clear_roles()
  })